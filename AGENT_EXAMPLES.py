"""
Example: Using the AI Agents
=============================
Quick examples of how to use each agent.
"""

import json
from agent import (
    OptimizerAgent, AnomalyAgent, ForecasterAgent,
    NLQAgent, ReporterAgent, AnalyzerAgent
)


def example_optimizer():
    """Example: Get optimization recommendations."""
    print("\n=== Optimizer Agent ===")
    
    agent = OptimizerAgent(tenant_id="example-tenant")
    
    # Prepare data
    cost_data = {
        "total_30d": 5000,
        "by_service": {
            "EC2": 2500,
            "RDS": 1500,
            "S3": 500,
            "Data Transfer": 500
        }
    }
    
    resource_data = {
        "total_resources": 25,
        "by_type": {
            "ec2_instances": 12,
            "rds_instances": 3,
            "s3_buckets": 5,
            "ebs_volumes": 5
        }
    }
    
    idle_resources = [
        {"resource_id": "i-0abc123", "type": "t3.xlarge", "monthly_cost": 45.50},
        {"resource_id": "vol-xyz789", "type": "gp3", "monthly_cost": 15.00}
    ]
    
    # Run agent
    result = agent.run(
        cost_data=cost_data,
        resource_data=resource_data,
        idle_resources=idle_resources
    )
    
    if result.success:
        print(f"✓ Generated {len(result.data.get('recommendations', []))} recommendations")
        print(f"  Cost: ${result.cost_usd:.4f}")
        print(f"  Tokens: {result.tokens_used}")
    else:
        print(f"✗ Failed: {result.error}")


def example_anomaly_detector():
    """Example: Detect cost anomalies."""
    print("\n=== Anomaly Detector Agent ===")
    
    agent = AnomalyAgent(tenant_id="example-tenant")
    
    historical_data = {
        "avg_daily": 166.67,
        "std_dev": 25,
        "min": 120,
        "max": 250
    }
    
    current_data = {
        "days": 7,
        "total": 2100,
        "daily_avg": 300,
        "peak": 450,
        "low": 200
    }
    
    baseline_stats = {
        "ec2_avg": 83,
        "rds_avg": 50,
        "s3_avg": 25,
        "other_avg": 9
    }
    
    result = agent.run(
        historical_data=historical_data,
        current_data=current_data,
        baseline_stats=baseline_stats
    )
    
    if result.success:
        print(f"✓ Detected {len(result.data.get('anomalies', []))} anomalies")
        print(f"  Cost: ${result.cost_usd:.4f}")
    else:
        print(f"✗ Failed: {result.error}")


def example_forecaster():
    """Example: Forecast spending."""
    print("\n=== Forecaster Agent ===")
    
    agent = ForecasterAgent(tenant_id="example-tenant")
    
    # Last 60 days of daily spend
    historical_spend = [
        150, 155, 160, 158, 165, 170, 168, 172,
        175, 178, 180, 182, 185, 188, 190, 192
    ] + [195] * 44  # 60 days total
    
    current_spend = 2950  # Already spent this month
    budget = 8000
    days_remaining = 15
    
    result = agent.run(
        historical_spend=historical_spend,
        current_spend=current_spend,
        budget=budget,
        days_remaining=days_remaining
    )
    
    if result.success:
        forecast = result.data
        print(f"✓ Forecast generated")
        print(f"  Projected month-end: ${forecast.get('projected_month_end_usd', 0):.2f}")
        print(f"  Budget breach probability: {forecast.get('budget_breach_probability', 0)*100:.1f}%")
        print(f"  Cost: ${result.cost_usd:.4f}")
    else:
        print(f"✗ Failed: {result.error}")


def example_nlq():
    """Example: Natural language query."""
    print("\n=== Natural Language Query Agent ===")
    
    agent = NLQAgent(tenant_id="example-tenant")
    
    question = "How much did I spend on EC2 last month?"
    
    cost_data = {
        "ec2_last_month": 2500,
        "total_last_month": 5000,
        "ec2_this_month": 2100,
        "by_region": {
            "us-east-1": 1500,
            "us-west-2": 600,
            "eu-west-1": 400
        }
    }
    
    result = agent.run(
        question=question,
        cost_data=cost_data,
        metadata={"period": "last month", "timezone": "UTC"}
    )
    
    if result.success:
        print(f"✓ Answer generated")
        print(f"  Answer: {result.data.get('answer', 'N/A')[:100]}...")
        print(f"  Confidence: {result.data.get('confidence', 0):.2f}")
        print(f"  Cost: ${result.cost_usd:.4f}")
    else:
        print(f"✗ Failed: {result.error}")


def example_reporter():
    """Example: Generate a report."""
    print("\n=== Reporter Agent ===")
    
    agent = ReporterAgent(tenant_id="example-tenant")
    
    cost_summary = {
        "total": 5000,
        "trend": "↑ 15% week-over-week",
        "top_services": ["EC2", "RDS", "Data Transfer"],
        "budget_status": "80% of monthly budget"
    }
    
    recommendations = [
        {"title": "Stop idle EC2 instances", "savings": 150},
        {"title": "Optimize RDS instance size", "savings": 200}
    ]
    
    anomalies = [
        {"title": "Data transfer spike on 2026-06-01", "severity": "warning"}
    ]
    
    result = agent.run(
        report_type="weekly",
        period="June 1-7, 2026",
        cost_summary=cost_summary,
        recommendations=recommendations,
        anomalies=anomalies
    )
    
    if result.success:
        report = result.data
        print(f"✓ Report generated: {report.get('title', 'N/A')}")
        print(f"  Sections: {len(report.get('sections', []))}")
        print(f"  Cost: ${result.cost_usd:.4f}")
    else:
        print(f"✗ Failed: {result.error}")


def example_analyzer():
    """Example: Root cause analysis."""
    print("\n=== Analyzer Agent ===")
    
    agent = AnalyzerAgent(tenant_id="example-tenant")
    
    anomaly = {
        "description": "EC2 costs increased 275% on 2026-06-02",
        "current_value": 412,
        "baseline_value": 150
    }
    
    resources = [
        {"action": "created", "resource_id": "i-new123", "type": "t3.large", "count": 19}
    ]
    
    timeline = {
        "anomaly_start": "2026-06-02 14:00",
        "peak": "2026-06-02 18:00",
        "resource_launch": "2026-06-02 13:45"
    }
    
    result = agent.run(
        anomaly=anomaly,
        resources=resources,
        timeline=timeline
    )
    
    if result.success:
        analysis = result.data
        print(f"✓ Analysis complete")
        print(f"  Probable cause: {analysis.get('probable_cause', 'Unknown')[:80]}...")
        print(f"  Confidence: {analysis.get('confidence', 0):.2f}")
        print(f"  Cost: ${result.cost_usd:.4f}")
    else:
        print(f"✗ Failed: {result.error}")


if __name__ == "__main__":
    print("CloudCostMonitor AI Agents — Examples")
    print("=" * 50)
    print("\nNote: Set CLAUDE_API_KEY or OPENAI_API_KEY environment variable first")
    
    # Uncomment to run examples:
    # example_optimizer()
    # example_anomaly_detector()
    # example_forecaster()
    # example_nlq()
    # example_reporter()
    # example_analyzer()
    
    print("\n✓ All example functions defined. Uncomment above to test.")
