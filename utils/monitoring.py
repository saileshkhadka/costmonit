"""
AWS Cost Monitor Helper
=======================
Provides a lightweight AI-backed monitoring workflow for cost summaries,
resource guidance, and optimization recommendations.
"""

import logging
from typing import Optional, Dict, Any

from agent import OptimizerAgent
from utils.db_helpers import AgentDatabase

log = logging.getLogger("costmonitor.monitoring")


def format_money(value: float) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def build_overview(cost_data: dict, resource_data: dict, idle_resources: list) -> dict:
    total_spend = sum(format_money(item.get("total")) for item in cost_data.get("by_service", []))
    top_services = [
        {
            "service": item.get("service"),
            "service_group": item.get("service_group"),
            "total_usd": format_money(item.get("total")),
        }
        for item in sorted(cost_data.get("by_service", []), key=lambda x: format_money(x.get("total")), reverse=True)[:10]
    ]

    top_regions = [
        {
            "region": item.get("region"),
            "total_usd": format_money(item.get("total")),
        }
        for item in sorted(cost_data.get("daily", []), key=lambda x: format_money(x.get("total")), reverse=True)[:10]
    ]

    return {
        "total_30d_usd": format_money(total_spend),
        "service_count": len(cost_data.get("by_service", [])),
        "idle_resources": len(idle_resources),
        "total_resource_types": len(resource_data.get("resources_by_type", [])),
        "top_services": top_services,
        "top_regions": top_regions,
        "resource_summary": resource_data,
    }


def run_monitoring_insights(
    tenant_id: str,
    db_url: str,
    aws_account_id: Optional[str] = None,
    days: int = 30,
    save_recommendations: bool = False,
) -> dict:
    """Run the monitoring workflow and return AI-backed insights."""
    db = AgentDatabase(db_url)

    cost_data = db.get_cost_data(tenant_id, aws_account_id, days)
    resource_data = db.get_resource_inventory_summary(tenant_id, aws_account_id)
    idle_resources = db.get_idle_resources(tenant_id, aws_account_id)

    overview = build_overview(cost_data, resource_data, idle_resources)

    if overview["total_30d_usd"] <= 0 and not resource_data.get("resources_by_type"):
        return {
            "success": False,
            "message": "No AWS cost or resource data available for the requested tenant/account.",
            "overview": overview,
            "recommendations": [],
        }

    agent = OptimizerAgent(tenant_id=tenant_id)
    agent_result = agent.run(
        cost_data=cost_data,
        resource_data=resource_data,
        idle_resources=idle_resources,
    )

    recommendations = []
    if agent_result.success:
        recommendations = agent_result.data.get("recommendations", []) or []
        if save_recommendations:
            db.save_recommendations(
                tenant_id=tenant_id,
                aws_account_id=aws_account_id,
                agent_type="optimizer",
                recommendations=recommendations,
            )

    return {
        "success": agent_result.success,
        "overview": overview,
        "recommendations": recommendations,
        "ai_metadata": {
            "tokens_used": agent_result.tokens_used,
            "cost_usd": agent_result.cost_usd,
            "model": agent_result.model,
            "error": agent_result.error,
        },
    }
