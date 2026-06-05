"""
Optimizer Agent
===============
Analyzes resource utilization and recommends cost-saving opportunities.
"""

import json
import logging
from typing import Dict, Any

from .base_agent import BaseAgent, AgentResult
from .prompts import OptimizerPrompts

log = logging.getLogger("costmonitor.agents")


class OptimizerAgent(BaseAgent):
    """AI agent for cost optimization recommendations."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "optimizer")

    def get_system_prompt(self) -> str:
        return OptimizerPrompts.SYSTEM

    def build_user_prompt(self, cost_data: dict, resource_data: dict, idle_resources: list) -> str:
        return OptimizerPrompts.build_user_prompt(cost_data, resource_data, idle_resources)

    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON recommendations from Claude response."""
        # Extract JSON from response (may contain markdown code blocks)
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()

        recommendations = json.loads(json_str)
        return {"recommendations": recommendations}

    def run(self, cost_data: dict, resource_data: dict, idle_resources: list = None) -> AgentResult:
        """
        Analyze costs and resources to generate optimization recommendations.
        
        Args:
            cost_data: Cost breakdown by service, region, etc.
            resource_data: Resource inventory with utilization metrics
            idle_resources: List of identified idle resources
            
        Returns:
            AgentResult with list of recommendations
        """
        if idle_resources is None:
            idle_resources = []

        log.info(f"[{self.agent_type}] Running optimization analysis for tenant {self.tenant_id}")

        user_prompt = self.build_user_prompt(
            cost_data=cost_data,
            resource_data=resource_data,
            idle_resources=idle_resources,
        )

        result = self.call_ai(user_prompt)

        if result.success:
            log.info(f"[{self.agent_type}] Generated {len(result.data.get('recommendations', []))} recommendations")
        else:
            log.error(f"[{self.agent_type}] Failed: {result.error}")

        return result
