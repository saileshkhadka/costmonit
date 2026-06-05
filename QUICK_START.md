# 🚀 CloudCostMonitor AI Agents — Quick Start

## What You Now Have

6 AI agents ready to analyze AWS costs:
- 🎯 **Optimizer** — Find cost-saving opportunities
- 🚨 **Anomaly Detector** — Spot unusual spending
- 📈 **Forecaster** — Predict month-end spending
- 🗣️ **NLQ** — Answer questions about costs
- 📊 **Reporter** — Generate executive reports
- 🔬 **Analyzer** — Root cause analysis

## Setup (3 Steps)

### 1. Install packages
```bash
cd /Users/dch-devops/projects/test-devops/costm
pip install -r requirements.txt
```

### 2. Set your API key
```bash
export CLAUDE_API_KEY=sk-ant-YOUR_KEY_HERE
# OR for OpenAI:
export OPENAI_API_KEY=sk-YOUR_KEY_HERE
```

### 3. Update database
```bash
psql -d costmonitor -f schema.sql
# This adds: ai_recommendations, anomaly_events, forecast_records, agent_runs, query_cache
```

## Test an Agent (Right Now!)

```python
python3 << 'PYTHON'
from agent import OptimizerAgent

# Create agent
agent = OptimizerAgent(tenant_id="test-company")

# Sample data
cost_data = {
    "ec2": 2500,
    "rds": 1500,
    "s3": 500,
}

resource_data = {
    "ec2_instances": 12,
    "idle": 3,
}

idle_resources = [
    {"id": "i-abc123", "monthly_cost": 45.50},
]

# Run it!
result = agent.run(
    cost_data=cost_data,
    resource_data=resource_data,
    idle_resources=idle_resources
)

print(f"✓ Success: {result.success}")
print(f"$ Cost: ${result.cost_usd:.4f}")
print(f"📊 Recommendations: {len(result.data.get('recommendations', []))}")

PYTHON
```

## Use Each Agent

### Optimizer
```python
from agent import OptimizerAgent
agent = OptimizerAgent(tenant_id="my-company")
result = agent.run(cost_data={...}, resource_data={...}, idle_resources=[...])
```

### Anomaly Detector
```python
from agent import AnomalyAgent
agent = AnomalyAgent(tenant_id="my-company")
result = agent.run(historical_data={...}, current_data={...}, baseline_stats={...})
```

### Forecaster
```python
from agent import ForecasterAgent
agent = ForecasterAgent(tenant_id="my-company")
result = agent.run(historical_spend=[...], current_spend=2950, budget=8000, days_remaining=15)
```

## Save Results to Database

```python
from utils.db_helpers import AgentDatabase

db = AgentDatabase("postgresql://user:password@localhost:5432/costmonitor")

# Save recommendations
db.save_recommendations(
    tenant_id="my-company",
    aws_account_id="123456789012",
    agent_type="optimizer",
    recommendations=result.data.get("recommendations", [])
)
```

## Result Format

Every agent returns:
```python
result.success         # True if succeeded
result.data            # Dict with parsed output
result.tokens_used     # Tokens used
result.cost_usd        # Cost in USD (e.g., 0.0456)
result.error           # Error message if failed
result.model           # Model used
```

## Files

```
agent/
  base_agent.py        — Framework (API calls, retries, cost tracking)
  optimizer.py         — Cost-saving recommendations
  anomaly.py           — Anomaly detection
  forecaster.py        — Spending forecasts
  nlq.py               — Natural language queries
  reporter.py          — Report generation
  analyzer.py          — Root cause analysis
  prompts.py           — AI prompts

utils/
  db_helpers.py        — Save results to Postgres

schema.sql            — New database tables
requirements.txt      — New dependencies
env.example           — Configuration
AGENTS_README.md      — Full documentation
AGENT_EXAMPLES.py     — Complete examples
```

## Next: Phase 3

Add FastAPI endpoints to expose agents via HTTP:

```python
@app.post("/agents/optimizer/run")
def run_optimizer(tenant_id: str, cost_data: dict):
    agent = OptimizerAgent(tenant_id)
    result = agent.run(cost_data=cost_data, ...)
    return result.data
```

## Get Started

1. Install: `pip install -r requirements.txt`
2. Set API key: `export CLAUDE_API_KEY=sk-ant-...`
3. Update DB: `psql -d costmonitor -f schema.sql`
4. Read docs: `cat AGENTS_README.md`
5. See examples: `cat AGENT_EXAMPLES.py`

---

**You're all set! 🚀**
