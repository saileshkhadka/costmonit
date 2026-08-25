"""
CloudCostMonitor — FastAPI Backend
====================================
All API endpoints your React dashboard will consume.

Run:
    uvicorn main:app --reload --port 8000

Docs auto-available at:
    http://localhost:8000/docs

Requirements:
    pip install fastapi uvicorn psycopg2-binary python-jose[cryptography] passlib[bcrypt] python-dotenv
"""

import os
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("costmonitor.api")

# AI agents + DB helpers
from agent import (
    OptimizerAgent, AnomalyAgent, ForecasterAgent,
    NLQAgent, ReporterAgent, AnalyzerAgent,
)
from utils.db_helpers import AgentDatabase
from utils.monitoring import run_monitoring_insights
from analysis import run_agent

app = FastAPI(
    title="CloudCostMonitor API",
    version="0.1.0",
    description="AWS cost monitoring and analytics API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", os.getenv("FRONTEND_URL", "")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
DB_URL = os.getenv("DB_URL", "postgresql://postgres:password@localhost:5432/costmonitor")
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer()


# ─────────────────────────────────────────────
# Database helper
# ─────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def create_token(user_id: str, tenant_id: str) -> str:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
):
    """Decode JWT and return {user_id, tenant_id}. Raises 401 on any failure."""
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id")
        if not user_id or not tenant_id:
            raise JWTError("Required claims are missing")
        return {"user_id": user_id, "tenant_id": tenant_id}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.post("/v1/agents/{agent_type}/run")
def run_agent_endpoint(
    agent_type: str,
    payload: dict,
    auth=Depends(get_current_user),
):
    """Run an AI agent (manual trigger). Saves the agent run to the DB.

    Body: arbitrary JSON forwarded to the agent's `run()` method.
    """
    db = AgentDatabase(DB_URL)

    try:
        result = run_agent(agent_type, auth["tenant_id"], payload or {})
    except Exception as e:
        # Record the failure and return 500
        try:
            db.save_agent_run(auth["tenant_id"], agent_type, "manual", "error", payload or {}, {}, str(e))
        except Exception:
            log.exception("Failed to persist failed agent run")
        raise HTTPException(status_code=500, detail=str(e))

    status = "success" if result.success else "error"
    try:
        db.save_agent_run(
            auth["tenant_id"], agent_type, "manual", status,
            payload or {}, result.data, result.error, result.tokens_used, result.cost_usd, result.model,
        )
    except Exception:
        log.exception("Failed to persist agent run")

    return {
        "success": result.success,
        "data": result.data,
        "tokens_used": result.tokens_used,
        "cost_usd": result.cost_usd,
        "error": result.error,
    }


@app.get("/v1/monitoring/insights")
def monitoring_insights(
    aws_account_id: Optional[str] = None,
    days: int = 30,
    save_recommendations: bool = False,
    auth=Depends(get_current_user),
):
    """Return overall AWS cost monitoring insights and AI recommendations."""
    result = run_monitoring_insights(
        tenant_id=auth["tenant_id"],
        db_url=DB_URL,
        aws_account_id=aws_account_id,
        days=days,
        save_recommendations=save_recommendations,
    )

    if not result["success"]:
        raise HTTPException(404, detail=result["message"])

    return result


# ─────────────────────────────────────────────
# Pydantic schemas (request / response models)
# ─────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    company_name: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class ConnectAccountRequest(BaseModel):
    display_name: str
    aws_account_id: str
    role_arn: str
    external_id: str

class CreateBudgetRequest(BaseModel):
    name: str
    aws_account_id: Optional[str] = None
    service_group: Optional[str] = None
    region: Optional[str] = None
    limit_usd: float
    period: str = "monthly"
    alert_at_pct: int = 80


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────────────────────────
# Auth endpoints
# ─────────────────────────────────────────────

@app.post("/v1/auth/register", status_code=201)
def register(body: RegisterRequest, db=Depends(get_db)):
    """Register a new tenant + owner user."""
    with db:
        with db.cursor() as cur:
            # Check email not taken
            cur.execute("SELECT id FROM users WHERE email = %s", (body.email,))
            if cur.fetchone():
                raise HTTPException(400, "Email already registered")

            # Create tenant
            tenant_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO tenants (id, name, email) VALUES (%s, %s, %s)",
                (tenant_id, body.company_name, body.email),
            )

            # Create owner user
            user_id = str(uuid.uuid4())
            cur.execute(
                """INSERT INTO users (id, tenant_id, email, name, role, password_hash)
                   VALUES (%s, %s, %s, %s, 'owner', %s)""",
                (user_id, tenant_id, body.email, body.name,
                 pwd_context.hash(body.password)),
            )

    return {
        "token": create_token(user_id, tenant_id),
        "user_id": user_id,
        "tenant_id": tenant_id,
    }


@app.post("/v1/auth/login")
def login(body: LoginRequest, db=Depends(get_db)):
    """Login and receive a JWT."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, tenant_id, password_hash FROM users WHERE email = %s",
            (body.email,),
        )
        user = cur.fetchone()

    if not user or not pwd_context.verify(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    return {
        "token": create_token(user["id"], user["tenant_id"]),
        "user_id": user["id"],
        "tenant_id": user["tenant_id"],
    }


# ─────────────────────────────────────────────
# AWS Account management
# ─────────────────────────────────────────────

@app.get("/v1/accounts")
def list_accounts(auth=Depends(get_current_user), db=Depends(get_db)):
    """List all connected AWS accounts for this tenant."""
    with db.cursor() as cur:
        cur.execute(
            """SELECT id, aws_account_id, account_alias, display_name,
                      status, last_synced_at, last_error, created_at
               FROM aws_accounts
               WHERE tenant_id = %s
               ORDER BY created_at DESC""",
            (auth["tenant_id"],),
        )
        return {"accounts": cur.fetchall()}


@app.post("/v1/accounts", status_code=201)
def connect_account(
    body: ConnectAccountRequest,
    background_tasks: BackgroundTasks,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Connect a new AWS account.
    Saves the IAM role ARN + external ID, then triggers a background sync.
    """
    account_id = str(uuid.uuid4())
    with db:
        with db.cursor() as cur:
            # Check not already connected
            cur.execute(
                "SELECT id FROM aws_accounts WHERE tenant_id = %s AND aws_account_id = %s",
                (auth["tenant_id"], body.aws_account_id),
            )
            if cur.fetchone():
                raise HTTPException(400, "This AWS account is already connected")

            cur.execute(
                """INSERT INTO aws_accounts
                   (id, tenant_id, aws_account_id, display_name, role_arn, external_id, status)
                   VALUES (%s, %s, %s, %s, %s, %s, 'pending')""",
                (account_id, auth["tenant_id"], body.aws_account_id,
                 body.display_name, body.role_arn, body.external_id),
            )

    # Trigger first sync in background (non-blocking)
    background_tasks.add_task(trigger_sync, auth["tenant_id"], body.aws_account_id)

    return {"id": account_id, "status": "pending", "message": "Sync started"}


@app.delete("/v1/accounts/{aws_account_id}", status_code=204)
def disconnect_account(
    aws_account_id: str,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """Disconnect an AWS account. Does not delete historical cost data."""
    with db:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM aws_accounts WHERE tenant_id = %s AND aws_account_id = %s",
                (auth["tenant_id"], aws_account_id),
            )


# ─────────────────────────────────────────────
# Cost data endpoints
# ─────────────────────────────────────────────

@app.get("/v1/costs/summary")
def cost_summary(
    aws_account_id: Optional[str] = None,
    period_days: int = 30,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Total spend for the period, grouped by service_group.
    Also returns % change vs previous period.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=period_days)
    prev_start = start - timedelta(days=period_days)

    account_filter = ""
    params_current = [auth["tenant_id"], str(start), str(end)]
    params_prev = [auth["tenant_id"], str(prev_start), str(start)]

    if aws_account_id:
        account_filter = "AND aws_account_id = %s"
        params_current.append(aws_account_id)
        params_prev.append(aws_account_id)

    with db.cursor() as cur:
        # Current period
        cur.execute(
            f"""SELECT service_group, SUM(cost_usd) AS total_usd
                FROM cost_records
                WHERE tenant_id = %s AND date >= %s AND date < %s
                  AND granularity = 'DAILY' {account_filter}
                GROUP BY service_group
                ORDER BY total_usd DESC""",
            params_current,
        )
        current = {r["service_group"]: float(r["total_usd"]) for r in cur.fetchall()}

        # Previous period (for % change)
        cur.execute(
            f"""SELECT service_group, SUM(cost_usd) AS total_usd
                FROM cost_records
                WHERE tenant_id = %s AND date >= %s AND date < %s
                  AND granularity = 'DAILY' {account_filter}
                GROUP BY service_group""",
            params_prev,
        )
        previous = {r["service_group"]: float(r["total_usd"]) for r in cur.fetchall()}

    # Build response with % change
    breakdown = []
    for group, total in current.items():
        prev = previous.get(group, 0.0)
        pct_change = ((total - prev) / prev * 100) if prev > 0 else None
        breakdown.append({
            "service_group": group,
            "total_usd": round(total, 2),
            "prev_total_usd": round(prev, 2),
            "pct_change": round(pct_change, 1) if pct_change is not None else None,
        })

    total_spend = sum(current.values())
    return {
        "period_days": period_days,
        "total_usd": round(total_spend, 2),
        "breakdown": breakdown,
    }


@app.get("/v1/costs/daily")
def daily_costs(
    aws_account_id: Optional[str] = None,
    days: int = 30,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """Daily spend totals — for the trend line chart."""
    start = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()

    account_filter = ""
    params = [auth["tenant_id"], start]
    if aws_account_id:
        account_filter = "AND aws_account_id = %s"
        params.append(aws_account_id)

    with db.cursor() as cur:
        cur.execute(
            f"""SELECT date, SUM(cost_usd) AS total_usd
                FROM cost_records
                WHERE tenant_id = %s AND date >= %s
                  AND granularity = 'DAILY' {account_filter}
                GROUP BY date
                ORDER BY date ASC""",
            params,
        )
        rows = cur.fetchall()

    return {
        "days": days,
        "data": [{"date": str(r["date"]), "total_usd": round(float(r["total_usd"]), 2)} for r in rows],
    }


@app.get("/v1/costs/services")
def top_services(
    aws_account_id: Optional[str] = None,
    days: int = 30,
    limit: int = 20,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """Top services by spend — for the service breakdown table."""
    start = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()

    account_filter = ""
    params = [auth["tenant_id"], start]
    if aws_account_id:
        account_filter = "AND aws_account_id = %s"
        params.append(aws_account_id)
    params.append(limit)

    with db.cursor() as cur:
        cur.execute(
            f"""SELECT service, service_group,
                       SUM(cost_usd) AS total_usd,
                       COUNT(DISTINCT date) AS active_days
                FROM cost_records
                WHERE tenant_id = %s AND date >= %s
                  AND granularity = 'DAILY' {account_filter}
                GROUP BY service, service_group
                ORDER BY total_usd DESC
                LIMIT %s""",
            params,
        )
        rows = cur.fetchall()

    return {
        "services": [
            {
                "service": r["service"],
                "service_group": r["service_group"],
                "total_usd": round(float(r["total_usd"]), 2),
                "active_days": r["active_days"],
            }
            for r in rows
        ]
    }


@app.get("/v1/costs/by-region")
def costs_by_region(
    aws_account_id: Optional[str] = None,
    days: int = 30,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """Spend breakdown by AWS region."""
    start = (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()

    account_filter = ""
    params = [auth["tenant_id"], start]
    if aws_account_id:
        account_filter = "AND aws_account_id = %s"
        params.append(aws_account_id)

    with db.cursor() as cur:
        cur.execute(
            f"""SELECT region, SUM(cost_usd) AS total_usd
                FROM cost_records
                WHERE tenant_id = %s AND date >= %s
                  AND granularity = 'DAILY' {account_filter}
                GROUP BY region
                ORDER BY total_usd DESC""",
            params,
        )
        rows = cur.fetchall()

    return {
        "regions": [{"region": r["region"], "total_usd": round(float(r["total_usd"]), 2)} for r in rows]
    }


# ─────────────────────────────────────────────
# Budgets & Alerts
# ─────────────────────────────────────────────

@app.get("/v1/budgets")
def list_budgets(auth=Depends(get_current_user), db=Depends(get_db)):
    """List all budgets for this tenant."""
    with db.cursor() as cur:
        cur.execute(
            """SELECT id, name, aws_account_id, service_group, region,
                      limit_usd, period, alert_at_pct, is_active, created_at
               FROM budgets
               WHERE tenant_id = %s
               ORDER BY created_at DESC""",
            (auth["tenant_id"],),
        )
        return {"budgets": cur.fetchall()}


@app.post("/v1/budgets", status_code=201)
def create_budget(
    body: CreateBudgetRequest,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """Create a new budget rule."""
    budget_id = str(uuid.uuid4())
    with db:
        with db.cursor() as cur:
            cur.execute(
                """INSERT INTO budgets
                   (id, tenant_id, aws_account_id, name, service_group, region,
                    limit_usd, period, alert_at_pct)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (budget_id, auth["tenant_id"], body.aws_account_id,
                 body.name, body.service_group, body.region,
                 body.limit_usd, body.period, body.alert_at_pct),
            )
    return {"id": budget_id, "name": body.name}


@app.delete("/v1/budgets/{budget_id}", status_code=204)
def delete_budget(
    budget_id: str,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    with db:
        with db.cursor() as cur:
            cur.execute(
                "DELETE FROM budgets WHERE id = %s AND tenant_id = %s",
                (budget_id, auth["tenant_id"]),
            )


@app.get("/v1/alerts")
def list_alerts(
    state: Optional[str] = None,
    limit: int = 50,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """List alert events. Filter by state: firing | resolved | acknowledged."""
    state_filter = "AND state = %s" if state else ""
    params = [auth["tenant_id"]]
    if state:
        params.append(state)
    params.append(limit)

    with db.cursor() as cur:
        cur.execute(
            f"""SELECT id, alert_type, severity, title, message,
                       current_value, threshold_value, percent_used,
                       state, triggered_at, resolved_at
                FROM alert_events
                WHERE tenant_id = %s {state_filter}
                ORDER BY triggered_at DESC
                LIMIT %s""",
            params,
        )
        return {"alerts": cur.fetchall()}


# ─────────────────────────────────────────────
# Manual sync trigger
# ─────────────────────────────────────────────

@app.post("/v1/accounts/{aws_account_id}/sync")
def trigger_manual_sync(
    aws_account_id: str,
    background_tasks: BackgroundTasks,
    auth=Depends(get_current_user),
    db=Depends(get_db),
):
    """Manually trigger a data sync for one account."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id FROM aws_accounts WHERE tenant_id = %s AND aws_account_id = %s",
            (auth["tenant_id"], aws_account_id),
        )
        if not cur.fetchone():
            raise HTTPException(404, "Account not found")

    background_tasks.add_task(trigger_sync, auth["tenant_id"], aws_account_id)
    return {"message": "Sync triggered", "aws_account_id": aws_account_id}


def trigger_sync(tenant_id: str, aws_account_id: str):
    """
    Background task: load account connection from DB and run ingestion.
    In production, replace this with a proper job queue (Celery, BullMQ, etc.).
    """
    import sys
    sys.path.append(os.path.dirname(__file__))
    from ingestion import AccountConnection, run_ingestion

    conn = psycopg2.connect(DB_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role_arn, external_id, account_alias FROM aws_accounts "
                "WHERE tenant_id = %s AND aws_account_id = %s",
                (tenant_id, aws_account_id),
            )
            row = cur.fetchone()
            if not row:
                return

        connection = AccountConnection(
            tenant_id=tenant_id,
            aws_account_id=aws_account_id,
            account_alias=row["account_alias"] or aws_account_id,
            role_arn=row["role_arn"],
            external_id=row["external_id"],
        )

        result = run_ingestion(connection, DB_URL)

        # Update sync status on the account
        with conn:
            with conn.cursor() as cur:
                if result["status"] == "success":
                    cur.execute(
                        "UPDATE aws_accounts SET status='active', last_synced_at=now(), last_error=NULL "
                        "WHERE tenant_id=%s AND aws_account_id=%s",
                        (tenant_id, aws_account_id),
                    )
                else:
                    error = "; ".join(result.get("errors", []))
                    cur.execute(
                        "UPDATE aws_accounts SET status='error', last_error=%s "
                        "WHERE tenant_id=%s AND aws_account_id=%s",
                        (error, tenant_id, aws_account_id),
                    )
    finally:
        conn.close()
