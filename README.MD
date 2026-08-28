# CloudCostMonitor

A lightweight AWS cost monitoring and AI analysis platform.

## What this project contains

- `iam-readonly-role.yaml` — CloudFormation template to deploy a read-only AWS role in a customer account.
- `ingestion.py` — data collector that:
  - assumes the customer's AWS IAM role
  - pulls Cost Explorer billing data
  - normalizes service names
  - upserts cost rows into Postgres
- `monitor.py` — command-line monitoring workflow for cost summaries, regional
  breakdowns, idle resources, and AI optimization recommendations.
- `schema.sql` — database schema for tenants, users, AWS connections, cost records, budgets, alerts, and AI analytics.
- `main.py` — FastAPI backend with JWT auth, account management, cost summaries,
  budgets and alerts, manual sync, and AI agent execution.
- `agent/` — AI agents for optimization, anomaly detection, forecasting,
  natural-language queries, reporting, and root-cause analysis.
- `requirements.txt` — Python dependencies.
- `env.example` — environment variable template.

## Quick start

1. Install Python dependencies:

```bash
cd /Users/dch-devops/projects/test-devops/costm
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

2. Create your `.env` file:

```bash
cp env.example .env
```

Then edit `.env` and set:
- `DB_URL`
- `JWT_SECRET`
- `CLAUDE_API_KEY` or `OPENAI_API_KEY`
- `PLATFORM_AWS_ACCOUNT_ID` for the platform account
- `TEST_TENANT_ID`, `TEST_ACCOUNT_ID`, `TEST_ROLE_ARN`, and `TEST_EXTERNAL_ID`
  when running `ingestion.py` directly
- `TENANT_ID` when using the monitoring CLI

3. Initialize the database:

```bash
psql "$DB_URL" -f schema.sql
```

4. Run ingestion:

```bash
.venv/bin/python ingestion.py
```

5. Start the API:

```bash
.venv/bin/uvicorn main:app --reload --port 8000
```

6. Open the API docs:

```text
http://localhost:8000/docs
```

7. Run the external AWS cost monitoring CLI:

```bash
export TENANT_ID=<your-tenant-id>
.venv/bin/python monitor.py --days 30 --aws-account-id <aws-account-id>
```

You can also save AI recommendations to the database with `--save-recs`.

## AWS connection

- Deploy `iam-readonly-role.yaml` in each customer AWS account and provide the
  resulting role ARN and external ID to the application.
- The role grants read-only access to Cost Explorer, CloudWatch, billing
  metadata, and common resource APIs including EC2, RDS, Lambda, ECS, EKS,
  Auto Scaling, ELB, DynamoDB, S3, and resource tags.
- Cost ingestion can be run from the CLI or triggered manually through the API.
- Cost Explorer monitoring works broadly by AWS service and region. Resource-
  level inventory collection is planned but is not yet implemented in
  `ingestion.py`.

## Monitoring and alerts

The monitoring workflow reports complete cost totals, top services, regional
totals, resource summaries, and AI optimization recommendations. Budget alerts
are evaluated after ingestion and saved to `alert_events` with duplicate active
alerts suppressed. The API exposes budget management and alert listing routes.

AI requests support Claude and OpenAI. Invalid AI JSON responses are reported as
failed runs instead of successful runs with unusable data.

## AI agent support

This project already includes AI agent support for:
- optimization recommendations
- anomaly detection
- forecasting
- natural language queries
- reporting
- root cause analysis

Use the new endpoint:

```bash
POST /v1/agents/{agent_type}/run
```

Example agent types:
- `optimizer`
- `anomaly`
- `forecaster`
- `nlq`
- `reporter`
- `analyzer`

The repository currently has no automated test suite. Compilation and focused
smoke checks should be run with the project virtual environment before deploy.

## Remaining work

- Add scheduled ingestion and scheduled AI jobs.
- Implement AWS resource inventory and CloudWatch utilization collection.
- Add Slack/email notification delivery for persisted alerts.
- Add frontend dashboard and deeper FinOps analysis such as tagging coverage,
  rightsizing, Savings Plans, reserved instances, and multi-account rollups.

## Useful files

- `AGENT_EXAMPLES.py` — examples of how to call each AI agent.
- `QUICK_START.md` — quick start guide for the AI agents.
- `sequence-to-use` — step-by-step usage instructions.
