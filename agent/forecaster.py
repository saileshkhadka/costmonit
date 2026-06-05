"""
Forecasting Agent
=================
Predicts future spending and budget breach risks.
"""

import json
import logging
from typing import Dict, Any

from .base_agent import BaseAgent, AgentResult
from .prompts import ForecasterPrompts

log = logging.getLogger("costmonitor.agents")


class ForecasterAgent(BaseAgent):
    """AI agent for spending forecasts and predictions."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "forecaster")

    def get_system_prompt(self) -> str:
        return ForecasterPrompts.SYSTEM

    def build_user_prompt(self, historical_spend: list, current_spend: float, 
                          budget: float, days_remaining: int) -> str:
        return ForecasterPrompts.build_user_prompt(
            historical_spend, current_spend, budget, days_remaining
        )

    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON forecast from Claude response."""
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()

        forecast = json.loads(json_str)
        return forecast

    def run(self, historical_spend: list, current_spend: float, 
            budget: float = None, days_remaining: int = None) -> AgentResult:
        """
        Generate spending forecast for month-end.
        
        Args:
            historical_spend: Daily spend amounts for last 60+ days
            current_spend: Total spent so far this month
            budget: Budget limit for the period
            days_remaining: Days left in billing period
            
        Returns:
            AgentResult with forecast data and budget breach probability
        """
        log.info(f"[{self.agent_type}] Generating forecast for tenant {self.tenant_id}")

        user_prompt = self.build_user_prompt(
            historical_spend=historical_spend,
            current_spend=current_spend,
            budget=budget or 10000,
            days_remaining=days_remaining or 15,
        )

        result = self.call_ai(user_prompt)

        if result.success:
            forecast = result.data
            log.info(f"[{self.agent_type}] Forecast: ${forecast.get('projected_month_end_usd', 0):.2f}")
            if forecast.get("budget_breach_probability", 0) > 0.5:
                log.warning(f"[{self.agent_type}] Budget breach risk: {forecast['budget_breach_probability']*100:.1f}%")
        else:
            log.error(f"[{self.agent_type}] Failed: {result.error}")

        return result
