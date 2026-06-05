# CloudCostMonitor AI Agents

Intelligent agents that analyze AWS spending patterns and generate insights, recommendations, and reports.

## Overview

The AI Agent framework includes **6 specialized agents**, each with a specific purpose:

### 🎯 Optimizer Agent
Analyzes resource utilization to identify cost-saving opportunities:
- Idle resources (not actively used)
- Oversized instances (high cost, low utilization)
- Unused services
- Reserved instance optimization gaps

**Output**: 3-5 actionable recommendations with estimated savings and priority levels.

### 🚨 Anomaly Detector Agent
Identifies unusual spending patterns:
- Spend spikes (>50% increase)
- New service activations
- Regional spending shifts
- Deviations from seasonal trends

**Output**: Detected anomalies with severity (info/warning/critical) and suspected causes.

### 📈 Forecasting Agent
Predicts future spending and budget breaches:
- Linear/exponential trend analysis
- Seasonality detection
- Budget projection
- Breach probability

**Output**: Month-end forecast with confidence intervals and warning indicators.

### 🗣️ Natural Language Query Agent
Answers cost questions in plain English:
- Understand user intent
- Query cost data
- Generate insights
- Provide recommendations

**Output**: Natural language answer with supporting data.

### 📊 Report Generator Agent
Creates executive-ready reports:
- Daily briefs
- Weekly summaries
- Monthly analysis
- Custom reports

**Output**: Formatted report with key metrics, insights, and action items.

### 🔬 Root Cause Analyzer Agent
Deep-dive investigation of cost events:
- Correlates cost changes with resource metrics
- Checks tag patterns
- Identifies newly launched services
- Suggests probable causes

**Output**: Structured cause analysis with confidence scores.

---

## Quick Start

### 1. Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Set your API key
export CLAUDE_API_KEY=sk-ant-...
# OR
export OPENAI_API_KEY=sk-...

# Configure other variables
export AI_MODEL=claude-3-5-sonnet-20241022
export AI_TEMPERATURE=0.7
```

### 2. Use an Agent

```python
from agent import OptimizerAgent

# Create agent
agent = OptimizerAgent(tenant_id="my-company")

# Prepare data
cost_data = {"EC2": 2500, "RDS": 1500}
resource_data = {"ec2_instances": 12, "rds_instances": 3}
idle_resources = [{"id": "i-abc123", "monthly_cost": 45.50}]

# Run analysis
result = agent.run(
    cost_data=cost_data,
    resource_data=resource_data,
    idle_resources=idle_resources
)

if result.success:
    for rec in result.data["recommendations"]:
        print(f"- {rec['title']}: ${rec['estimated_savings_monthly_usd']}/mo")
        print(f"  Priority: {rec['priority']} | Confidence: {rec['confidence_score']}")
else:
    print(f"Error: {result.error}")
```

### 3. Example: All Agents

See `AGENT_EXAMPLES.py` for complete working examples of each agent.

---

## Agent Specification

### BaseAgent (base_agent.py)

All agents inherit from `BaseAgent`, which provides:
- API integration (Claude/OpenAI with auto-selection)
- Retry logic with exponential backoff
- Token counting and cost tracking
- JSON parsing with error handling
- Standard result format (`AgentResult`)

### Agent Structure

Each agent implements:

```python
from agent import BaseAgent

class MyAgent(BaseAgent):
    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "my_agent_type")
    
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass
    
    def build_user_prompt(self, **kwargs) -> str:
        """Build the user message."""
        pass
    
    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse AI response into structured data."""
        pass
    
    def run(self, **kwargs) -> AgentResult:
        """Execute the agent."""
        pass
```

### AgentResult

All agents return a standardized `AgentResult`:

```python
@dataclass
class AgentResult:
    success: bool              # Whether execution succeeded
    data: Dict[str, Any]       # Parsed output data
    tokens_used: int           # Total tokens consumed
    cost_usd: float            # API cost in USD
    error: Optional[str]       # Error message if failed
    model: str                 # Model used (claude-3.5-sonnet, gpt-4, etc.)
```

---

## Configuration

### Environment Variables

```bash
# AI Provider
AI_PROVIDER=claude                          # claude | openai
CLAUDE_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Model & behavior
AI_MODEL=claude-3-5-sonnet-20241022        # Model to use
AI_MAX_TOKENS=2000                         # Max output tokens
AI_TEMPERATURE=0.7                         # 0=deterministic, 1=creative

# Retry & timeout
AGENT_MAX_RETRIES=3
AGENT_TIMEOUT_SECONDS=60
```

### Pricing (as of 2024)

**Claude Sonnet 3.5** (recommended):
- Input: $3 per 1M tokens
- Output: $15 per 1M tokens

**OpenAI GPT-4o**:
- Input: $2.50 per 1M tokens
- Output: $10 per 1M tokens

**OpenAI GPT-4**:
- Input: $30 per 1M tokens
- Output: $60 per 1M tokens

---

## Database Integration

Store all agent results using `AgentDatabase` helper:

```python
from utils.db_helpers import AgentDatabase

db = AgentDatabase(db_url)

# Save agent run
run_id = db.save_agent_run(
    tenant_id="my-company",
    agent_type="optimizer",
    trigger_type="manual",
    status="success",
    input_data={...},
    output_data={...},
    tokens_used=1234,
    cost_usd=0.0456
)

# Save recommendations
saved_count = db.save_recommendations(
    tenant_id="my-company",
    aws_account_id="123456789012",
    agent_type="optimizer",
    recommendations=[...]
)

# Save anomalies
anomaly_count = db.save_anomalies(
    tenant_id="my-company",
    aws_account_id="123456789012",
    anomalies=[...]
)

# Save forecast
forecast_id = db.save_forecast(
    tenant_id="my-company",
    aws_account_id="123456789012",
    forecast={...}
)
```

---

## Best Practices

### 1. Error Handling
Agents include retry logic, but always check `result.success`:

```python
result = agent.run(...)
if not result.success:
    log.error(f"Agent failed: {result.error}")
    # Serve cached data or fallback response
```

### 2. Cost Control
- Batch requests (run agents once/day, not per-request)
- Cache results (24h default)
- Use cheaper models for pre-filtering
- Monitor spending per tenant

### 3. Quality Assurance
- Test with sample data first
- Validate JSON parsing
- Monitor confidence scores
- Collect user feedback

### 4. Scaling
- Run agents asynchronously (background jobs)
- Limit concurrent agents (default: 2)
- Use database for audit trail
- Implement rate limiting

---

## API Endpoints (Coming in Phase 3)

```
GET    /recommendations                     - List recommendations
POST   /recommendations/refresh             - Trigger new analysis
POST   /recommendations/{id}/feedback       - Record user action

GET    /anomalies                          - List detected anomalies
POST   /anomalies/{id}/acknowledge         - Mark as reviewed

GET    /forecast                           - Current forecast
GET    /forecast/budget-breach             - Breach warnings

POST   /query                              - Natural language query
GET    /reports/daily|weekly|monthly       - Generate reports

GET    /agents/status                      - Agent health
GET    /agents/{type}/runs                 - Agent run history
```

---

## Development

### Adding a New Agent

1. Create `agent/my_agent.py`:
```python
from agent import BaseAgent, AgentResult
from agent.prompts import MyPrompts

class MyAgent(BaseAgent):
    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "my_agent")
    
    def get_system_prompt(self) -> str:
        return MyPrompts.SYSTEM
    
    def build_user_prompt(self, **kwargs) -> str:
        return MyPrompts.build_user_prompt(**kwargs)
    
    def parse_response(self, response_text: str) -> dict:
        # Extract JSON or parse response
        pass
    
    def run(self, **kwargs) -> AgentResult:
        prompt = self.build_user_prompt(**kwargs)
        return self.call_ai(prompt)
```

2. Add prompts to `agent/prompts.py`:
```python
class MyPrompts:
    SYSTEM = "You are a..."
    
    @staticmethod
    def build_user_prompt(...) -> str:
        return "..."
```

3. Export from `agent/__init__.py`:
```python
from .my_agent import MyAgent
__all__ = [..., "MyAgent"]
```

4. Test in `AGENT_EXAMPLES.py`

---

## Testing

### Unit Tests
```bash
pytest test/test_agents.py
```

### Example Runs
```bash
python AGENT_EXAMPLES.py
```

### Integration Test
```python
from agent import OptimizerAgent
from utils.db_helpers import AgentDatabase

db = AgentDatabase(db_url)
agent = OptimizerAgent("test-tenant")
result = agent.run(cost_data=..., resource_data=...)

if result.success:
    db.save_recommendations("test-tenant", "123456789012", "optimizer", 
                           result.data["recommendations"])
```

---

## Troubleshooting

### Agent times out
- Check API key validity
- Increase `AGENT_TIMEOUT_SECONDS`
- Check network connectivity
- Verify input data size

### JSON parsing fails
- Print `response.data.get("raw_response")`
- Check AI output format
- Adjust prompt for clearer instructions
- Try different model

### High costs
- Use cheaper model (Claude Sonnet instead of GPT-4)
- Reduce `AI_MAX_TOKENS`
- Implement caching
- Batch process instead of real-time

### Low confidence scores
- Provide more context data
- Use longer historical period
- Adjust `AI_TEMPERATURE` to 0.5
- Add validation logic

---

## What's Next

### Phase 3: API Integration
- Add FastAPI endpoints for each agent
- Wire up background job scheduler
- Implement recommendation feedback tracking
- Add agent run history & monitoring

### Phase 4: Advanced Features
- Multi-tenant cost aggregation
- Custom alert thresholds
- Integration with Slack/email
- Dashboard visualization
- Team-based recommendations

---

## Support

For issues or questions:
1. Check logs: `cat /var/log/costmonitor/*.log`
2. Review agent run history: `SELECT * FROM agent_runs ORDER BY created_at DESC`
3. Test with `AGENT_EXAMPLES.py`
4. Check API credentials are valid
