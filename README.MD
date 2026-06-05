# CloudCostMonitor

A lightweight AWS cost monitoring and AI analysis platform.

## What this project contains

- `iam-readonly-role.yaml` — CloudFormation template to deploy a read-only AWS role in a customer account.
- `ingestion.py` — data collector that:
  - assumes the customer's AWS IAM role
  - pulls Cost Explorer billing data
  - normalizes service names
  - upserts cost rows into Postgres
- `schema.sql` — database schema for tenants, users, AWS connections, cost records, budgets, alerts, and AI analytics.
- `main.py` — FastAPI backend with JWT auth, account management, cost summaries, budgets and alerts, manual sync, and AI agent execution.
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
- `PLATFORM_AWS_ACCOUNT_ID`
- `TEST_ROLE_ARN`
- `TEST_EXTERNAL_ID`

3. Initialize the database:

```bash
psql -d costmonitor -f schema.sql
```

4. Run ingestion:

```bash
python ingestion.py
```

5. Start the API:

```bash
uvicorn main:app --reload --port 8000
```

6. Open the API docs:

```text
http://localhost:8000/docs
```

## Notes

- `iam-readonly-role.yaml` is deployed in the customer’s AWS account once.
- The role grants read-only access to billing, cost, CloudWatch, EC2, RDS, Lambda, and other inventory APIs.
- `ingestion.py` runs hourly by design, but can be triggered manually via the API.

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

## Useful files

- `AGENT_EXAMPLES.py` — examples of how to call each AI agent.
- `QUICK_START.md` — quick start guide for the AI agents.
- `sequence-to-use` — step-by-step usage instructions.
