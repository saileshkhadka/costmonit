"""
CloudCostMonitor — AWS Ingestion Pipeline
==========================================
Pulls cost data from a customer AWS account via their
read-only IAM role, normalizes it, and upserts into Postgres.

Run directly:
    python ingestion.py

Or import run_ingestion() into your scheduler / FastAPI background task.

Requirements:
    pip install boto3 python-dateutil psycopg2-binary python-dotenv
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from typing import Optional

import boto3
from botocore.exceptions import ClientError, BotoCoreError
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("costmonitor.ingestion")


# ─────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────

@dataclass
class CostRecord:
    """One row in cost_records. One service + region + day + account."""
    id: str                           # deterministic SHA hash
    tenant_id: str
    aws_account_id: str
    account_alias: str
    date: str                         # YYYY-MM-DD
    granularity: str                  # DAILY | MONTHLY
    provider: str = "aws"
    service: str = ""
    service_group: str = ""
    region: str = "global"
    cost_usd: float = 0.0
    usage_quantity: float = 0.0
    usage_unit: str = ""
    tags: dict = field(default_factory=dict)
    ingested_at: str = ""
    raw_service_name: str = ""


@dataclass
class AccountConnection:
    """Customer AWS account connection details."""
    tenant_id: str
    aws_account_id: str
    account_alias: str
    role_arn: str        # arn:aws:iam::ACCOUNT_ID:role/CloudCostMonitor-ReadOnly
    external_id: str     # the UUID from the CloudFormation deploy


# ─────────────────────────────────────────────
# Service group normalization
# Maps AWS service names → clean categories
# ─────────────────────────────────────────────

SERVICE_GROUPS = {
    # Compute
    "Amazon EC2": "compute",
    "EC2 - Other": "compute",
    "AWS Lambda": "compute",
    "Amazon ECS": "compute",
    "Amazon EKS": "compute",
    "AWS Fargate": "compute",
    "Amazon Lightsail": "compute",
    "AWS Batch": "compute",

    # Storage
    "Amazon S3": "storage",
    "Amazon Simple Storage Service": "storage",
    "Amazon EBS": "storage",
    "Amazon Elastic Block Store": "storage",
    "Amazon EFS": "storage",
    "Amazon S3 Glacier": "storage",
    "Amazon FSx": "storage",
    "AWS Storage Gateway": "storage",

    # Database
    "Amazon RDS": "database",
    "Amazon Relational Database Service": "database",
    "Amazon DynamoDB": "database",
    "Amazon ElastiCache": "database",
    "Amazon Redshift": "database",
    "Amazon Aurora": "database",
    "Amazon DocumentDB": "database",
    "Amazon Neptune": "database",
    "Amazon MemoryDB": "database",

    # Network
    "Amazon CloudFront": "network",
    "Amazon Route 53": "network",
    "Amazon VPC": "network",
    "Amazon API Gateway": "network",
    "AWS Transit Gateway": "network",
    "Amazon Global Accelerator": "network",
    "AWS Direct Connect": "network",
    "AWS PrivateLink": "network",

    # AI / ML
    "Amazon SageMaker": "ai_ml",
    "Amazon Bedrock": "ai_ml",
    "Amazon Rekognition": "ai_ml",
    "Amazon Comprehend": "ai_ml",
    "Amazon Textract": "ai_ml",
    "Amazon Polly": "ai_ml",
    "Amazon Translate": "ai_ml",

    # Analytics
    "Amazon Athena": "analytics",
    "Amazon EMR": "analytics",
    "Amazon Kinesis": "analytics",
    "AWS Glue": "analytics",
    "Amazon QuickSight": "analytics",

    # Management
    "Amazon CloudWatch": "management",
    "AWS CloudTrail": "management",
    "AWS Config": "management",
    "AWS Systems Manager": "management",
    "AWS CloudFormation": "management",
    "AWS CodeBuild": "management",
    "AWS CodePipeline": "management",
}


def get_service_group(service_name: str) -> str:
    """Map raw AWS service name to a clean category."""
    if service_name in SERVICE_GROUPS:
        return SERVICE_GROUPS[service_name]
    lower = service_name.lower()
    if any(k in lower for k in ["ec2", "lambda", "ecs", "eks", "fargate", "compute"]):
        return "compute"
    if any(k in lower for k in ["s3", "storage", "ebs", "efs", "glacier"]):
        return "storage"
    if any(k in lower for k in ["rds", "dynamo", "database", "elasticache", "redshift"]):
        return "database"
    if any(k in lower for k in ["cloudfront", "route 53", "vpc", "api gateway", "network"]):
        return "network"
    if any(k in lower for k in ["sagemaker", "bedrock", "ai", "ml", "rekognition"]):
        return "ai_ml"
    return "other"


def make_record_id(aws_account_id: str, date: str, service: str, region: str) -> str:
    """Deterministic hash ID — safe to upsert the same record multiple times."""
    key = f"{aws_account_id}:{date}:{service}:{region}"
    return hashlib.sha256(key.encode()).hexdigest()[:20]


# ─────────────────────────────────────────────
# AWS session — assume customer's read-only role
# ─────────────────────────────────────────────

def get_assumed_session(connection: AccountConnection) -> boto3.Session:
    """
    Use STS AssumeRole to get temporary credentials for the customer account.
    The ExternalId MUST match what's in the IAM role's trust policy.
    Returns a boto3 session scoped to that account.
    """
    sts = boto3.client("sts")
    log.info(f"Assuming role for account {connection.aws_account_id}")

    try:
        response = sts.assume_role(
            RoleArn=connection.role_arn,
            RoleSessionName=f"CostMonitor-{connection.aws_account_id}",
            ExternalId=connection.external_id,
            DurationSeconds=3600,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDenied":
            raise PermissionError(
                f"Cannot assume role {connection.role_arn}. "
                "Verify the ExternalId and trust policy are correct."
            ) from e
        raise

    creds = response["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name="us-east-1",
    )


def get_account_alias(session: boto3.Session, account_id: str) -> str:
    """Get the human-readable account alias, fall back to account ID."""
    try:
        iam = session.client("iam")
        aliases = iam.list_account_aliases().get("AccountAliases", [])
        return aliases[0] if aliases else account_id
    except Exception:
        return account_id


# ─────────────────────────────────────────────
# Cost data pulls
# ─────────────────────────────────────────────

def pull_daily_costs(
    session: boto3.Session,
    connection: AccountConnection,
    days_back: int = 32,
) -> list[CostRecord]:
    """
    Pull daily cost breakdown from Cost Explorer.
    Groups by SERVICE and REGION.
    Goes back 32 days (overlap handles AWS's retroactive adjustments).
    """
    ce = session.client("ce", region_name="us-east-1")
    end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    account_alias = get_account_alias(session, connection.aws_account_id)
    ingested_at = datetime.now(timezone.utc).isoformat()

    log.info(f"Pulling daily costs {start_date} → {end_date} for {connection.aws_account_id}")

    records = []
    next_token = None

    while True:
        kwargs = dict(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="DAILY",
            Metrics=["UnblendedCost", "UsageQuantity"],
            GroupBy=[
                {"Type": "DIMENSION", "Key": "SERVICE"},
                {"Type": "DIMENSION", "Key": "REGION"},
            ],
            Filter={
                "Not": {
                    "Dimensions": {
                        "Key": "RECORD_TYPE",
                        "Values": ["Credit", "Refund"],
                    }
                }
            },
        )
        if next_token:
            kwargs["NextPageToken"] = next_token

        try:
            response = ce.get_cost_and_usage(**kwargs)
        except ClientError as e:
            log.error(f"Cost Explorer error: {e}")
            raise

        for period in response.get("ResultsByTime", []):
            day = period["TimePeriod"]["Start"]
            for group in period.get("Groups", []):
                service_name = group["Keys"][0] if len(group["Keys"]) > 0 else "Unknown"
                region = group["Keys"][1] if len(group["Keys"]) > 1 else "global"
                cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
                usage = float(group["Metrics"]["UsageQuantity"]["Amount"])
                unit = group["Metrics"]["UsageQuantity"].get("Unit", "")

                # Skip $0 rows
                if cost == 0.0 and usage == 0.0:
                    continue

                records.append(CostRecord(
                    id=make_record_id(connection.aws_account_id, day, service_name, region),
                    tenant_id=connection.tenant_id,
                    aws_account_id=connection.aws_account_id,
                    account_alias=account_alias,
                    date=day,
                    granularity="DAILY",
                    service=service_name,
                    service_group=get_service_group(service_name),
                    region=region if region != "NoRegion" else "global",
                    cost_usd=round(cost, 6),
                    usage_quantity=round(usage, 4),
                    usage_unit=unit,
                    ingested_at=ingested_at,
                    raw_service_name=service_name,
                ))

        next_token = response.get("NextPageToken")
        if not next_token:
            break

    log.info(f"Pulled {len(records)} daily records")
    return records


def pull_monthly_summary(
    session: boto3.Session,
    connection: AccountConnection,
    months_back: int = 6,
) -> list[CostRecord]:
    """
    Pull monthly cost totals — used for trend charts and forecasting.
    """
    ce = session.client("ce", region_name="us-east-1")
    now = datetime.now(timezone.utc)
    start_date = (now - relativedelta(months=months_back)).replace(day=1).strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")
    account_alias = get_account_alias(session, connection.aws_account_id)
    ingested_at = datetime.now(timezone.utc).isoformat()

    log.info(f"Pulling {months_back}-month summary for {connection.aws_account_id}")

    response = ce.get_cost_and_usage(
        TimePeriod={"Start": start_date, "End": end_date},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    records = []
    for period in response.get("ResultsByTime", []):
        month_start = period["TimePeriod"]["Start"]
        for group in period.get("Groups", []):
            service_name = group["Keys"][0]
            cost = float(group["Metrics"]["UnblendedCost"]["Amount"])
            if cost == 0.0:
                continue
            records.append(CostRecord(
                id=make_record_id(connection.aws_account_id, month_start, service_name, "global") + "_m",
                tenant_id=connection.tenant_id,
                aws_account_id=connection.aws_account_id,
                account_alias=account_alias,
                date=month_start,
                granularity="MONTHLY",
                service=service_name,
                service_group=get_service_group(service_name),
                region="global",
                cost_usd=round(cost, 4),
                ingested_at=ingested_at,
                raw_service_name=service_name,
            ))

    log.info(f"Pulled {len(records)} monthly records")
    return records


def pull_forecast(
    session: boto3.Session,
    connection: AccountConnection,
    days_ahead: int = 30,
) -> dict:
    """
    Forecast total spend for the next N days.
    Requires at least 1 month of historical data in Cost Explorer.
    """
    ce = session.client("ce", region_name="us-east-1")
    start = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    end = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    try:
        response = ce.get_cost_forecast(
            TimePeriod={"Start": start, "End": end},
            Metric="UNBLENDED_COST",
            Granularity="MONTHLY",
            PredictionIntervalLevel=80,
        )
        total = response.get("Total", {})
        intervals = response.get("ForecastResultsByTime", [{}])
        return {
            "account_id": connection.aws_account_id,
            "period_start": start,
            "period_end": end,
            "mean_usd": round(float(total.get("Amount", 0)), 2),
            "lower_usd": round(float(intervals[0].get("PredictionIntervalLowerBound", 0)), 2),
            "upper_usd": round(float(intervals[0].get("PredictionIntervalUpperBound", 0)), 2),
        }
    except ClientError as e:
        log.warning(f"Forecast unavailable for {connection.aws_account_id}: {e}")
        return {}


# ─────────────────────────────────────────────
# Database — upsert to Postgres
# ─────────────────────────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS cost_records (
    id               TEXT        PRIMARY KEY,
    tenant_id        UUID        NOT NULL,
    aws_account_id   TEXT        NOT NULL,
    account_alias    TEXT        NOT NULL DEFAULT '',
    date             DATE        NOT NULL,
    granularity      TEXT        NOT NULL DEFAULT 'DAILY',
    provider         TEXT        NOT NULL DEFAULT 'aws',
    service          TEXT        NOT NULL,
    service_group    TEXT        NOT NULL DEFAULT 'other',
    region           TEXT        NOT NULL DEFAULT 'global',
    cost_usd         NUMERIC(14,6) NOT NULL DEFAULT 0,
    usage_quantity   NUMERIC(16,4) NOT NULL DEFAULT 0,
    usage_unit       TEXT        NOT NULL DEFAULT '',
    tags             JSONB       NOT NULL DEFAULT '{}',
    ingested_at      TIMESTAMPTZ NOT NULL,
    raw_service_name TEXT        NOT NULL DEFAULT '',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_cr_account_date ON cost_records(aws_account_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_cr_tenant_date  ON cost_records(tenant_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_cr_group        ON cost_records(aws_account_id, service_group, date DESC);
"""

UPSERT_SQL = """
INSERT INTO cost_records (
    id, tenant_id, aws_account_id, account_alias,
    date, granularity, provider, service, service_group, region,
    cost_usd, usage_quantity, usage_unit,
    tags, ingested_at, raw_service_name
)
VALUES (
    %(id)s, %(tenant_id)s::uuid, %(aws_account_id)s, %(account_alias)s,
    %(date)s, %(granularity)s, %(provider)s, %(service)s, %(service_group)s, %(region)s,
    %(cost_usd)s, %(usage_quantity)s, %(usage_unit)s,
    %(tags)s, %(ingested_at)s, %(raw_service_name)s
)
ON CONFLICT (id) DO UPDATE SET
    cost_usd       = EXCLUDED.cost_usd,
    usage_quantity = EXCLUDED.usage_quantity,
    ingested_at    = EXCLUDED.ingested_at
;
"""


def upsert_records(records: list[CostRecord], db_url: str) -> int:
    """Bulk upsert records into Postgres. Safe to run multiple times."""
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        raise ImportError("Run: pip install psycopg2-binary")

    if not records:
        return 0

    conn = psycopg2.connect(db_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(CREATE_TABLE_SQL)
                rows = []
                for r in records:
                    row = asdict(r)
                    row["tags"] = json.dumps(row["tags"])
                    rows.append(row)
                psycopg2.extras.execute_batch(cur, UPSERT_SQL, rows, page_size=500)
                log.info(f"Upserted {len(rows)} records into cost_records")
                return len(rows)
    finally:
        conn.close()


# ─────────────────────────────────────────────
# Alerts — check budgets after every sync
# ─────────────────────────────────────────────

def check_budget_alerts(records: list[CostRecord], budgets: list[dict]) -> list[dict]:
    """
    Compare this month's spend against budget limits.

    budgets: list of dicts from your budgets table, e.g.:
    [{"id": "uuid", "name": "EC2 budget", "aws_account_id": "123...",
      "service_group": "compute", "limit_usd": 1000, "alert_at_pct": 80}]

    Returns: list of triggered alert dicts ready to send via Slack/email.
    """
    month_start = datetime.now(timezone.utc).strftime("%Y-%m-01")

    # Sum current month spend per account, service group, and region.
    spend: dict = {}
    for r in records:
        if r.date >= month_start and r.granularity == "DAILY":
            key = (r.aws_account_id, r.service_group, r.region)
            spend[key] = spend.get(key, 0.0) + r.cost_usd

    triggered = []
    for b in budgets:
        current = sum(
            amount
            for (account_id, service_group, region), amount in spend.items()
            if (b.get("aws_account_id") is None or account_id == b["aws_account_id"])
            and (b.get("service_group") is None or service_group == b["service_group"])
            and (b.get("region") is None or region == b["region"])
        )
        limit = float(b["limit_usd"])
        threshold = b.get("alert_at_pct", 80)
        pct = (current / limit * 100) if limit > 0 else 0

        if pct >= threshold:
            triggered.append({
                "budget_id": b["id"],
                "budget_name": b["name"],
                "aws_account_id": b["aws_account_id"],
                "service_group": b.get("service_group"),
                "current_usd": round(current, 2),
                "limit_usd": limit,
                "percent_used": round(pct, 1),
                "severity": "critical" if pct >= 100 else "warning",
                "triggered_at": datetime.now(timezone.utc).isoformat(),
                "message": (
                    f"Budget alert: '{b['name']}' is at {pct:.1f}% — "
                    f"${current:,.2f} of ${limit:,.2f}"
                ),
            })

    return triggered


# ─────────────────────────────────────────────
# Main job — full ingestion for one account
# ─────────────────────────────────────────────

def run_ingestion(connection: AccountConnection, db_url: str) -> dict:
    """
    Full ingestion pipeline for one customer AWS account.
    Safe to run multiple times (idempotent).

    Steps:
      1. Assume the customer's read-only IAM role via STS
      2. Pull 32 days of daily cost data
      3. Pull 6 months of monthly summaries
      4. Pull 30-day spend forecast
      5. Upsert everything into Postgres
      6. Return a summary dict
    """
    result = {
        "account_id": connection.aws_account_id,
        "tenant_id": connection.tenant_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "error",
        "daily_records": 0,
        "monthly_records": 0,
        "total_upserted": 0,
        "forecast": {},
        "errors": [],
    }

    try:
        # 1. Assume role
        session = get_assumed_session(connection)

        # 2. Daily costs
        daily = pull_daily_costs(session, connection)
        result["daily_records"] = len(daily)

        # 3. Monthly summary
        monthly = pull_monthly_summary(session, connection)
        result["monthly_records"] = len(monthly)

        # 4. Forecast
        result["forecast"] = pull_forecast(session, connection)

        # 5. Store
        all_records = daily + monthly
        result["total_upserted"] = upsert_records(all_records, db_url)

        # 6. Evaluate and persist budget alerts after the cost upsert.
        from utils.db_helpers import AgentDatabase
        db = AgentDatabase(db_url)
        budgets = db.get_active_budgets(connection.tenant_id, connection.aws_account_id)
        alerts = check_budget_alerts(daily, budgets)
        result["alerts"] = len(alerts)
        db.save_alert_events(connection.tenant_id, alerts)

        result["status"] = "success"
        result["completed_at"] = datetime.now(timezone.utc).isoformat()

    except PermissionError as e:
        result["errors"].append(f"IAM permission error: {e}")
        log.error(e)
    except (ClientError, BotoCoreError) as e:
        result["errors"].append(f"AWS API error: {e}")
        log.error(e)
    except Exception as e:
        result["errors"].append(f"Unexpected: {e}")
        log.exception(e)

    return result


# ─────────────────────────────────────────────
# Run as a standalone script
# ─────────────────────────────────────────────

if __name__ == "__main__":
    connection = AccountConnection(
        tenant_id=os.getenv("TEST_TENANT_ID", "00000000-0000-0000-0000-000000000000"),
        aws_account_id=os.getenv("TEST_ACCOUNT_ID", "123456789012"),
        account_alias="my-aws-account",
        role_arn=os.getenv("TEST_ROLE_ARN", "arn:aws:iam::123456789012:role/CloudCostMonitor-ReadOnly"),
        external_id=os.getenv("TEST_EXTERNAL_ID", "replace-with-your-external-id"),
    )

    db_url = os.getenv("DB_URL", "postgresql://postgres:password@localhost:5432/costmonitor")

    result = run_ingestion(connection, db_url)

    print("\n── Result ────────────────────────────────────")
    print(json.dumps(result, indent=2, default=str))

    if result.get("forecast"):
        f = result["forecast"]
        print(f"\n── 30-Day Forecast ───────────────────────────")
        print(f"  Estimated: ${f.get('mean_usd', 0):,.2f}")
        print(f"  Range:     ${f.get('lower_usd', 0):,.2f} — ${f.get('upper_usd', 0):,.2f}")
