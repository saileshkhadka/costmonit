"""
Anomaly Detector Agent
======================
Identifies unusual spending patterns and cost spikes.
"""

import json
import logging
from typing import Dict, Any

from .base_agent import BaseAgent, AgentResult
from .prompts import AnomalyPrompts

log = logging.getLogger("costmonitor.agents")


class AnomalyAgent(BaseAgent):
    """AI agent for detecting cost anomalies."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "anomaly")

    def get_system_prompt(self) -> str:
        return AnomalyPrompts.SYSTEM

    def build_user_prompt(self, historical_data: dict, current_data: dict, baseline_stats: dict) -> str:
        return AnomalyPrompts.build_user_prompt(historical_data, current_data, baseline_stats)

    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON anomalies from Claude response."""
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()

        anomalies = json.loads(json_str)
        return {"anomalies": anomalies}

    def run(self, historical_data: dict, current_data: dict, baseline_stats: dict) -> AgentResult:
        """
        Detect cost anomalies by comparing current spend against historical patterns.
        
        Args:
            historical_data: Historical spending patterns (90 days)
            current_data: Recent spending data (7 days)
            baseline_stats: Baseline metrics (avg, std dev, etc.)
            
        Returns:
            AgentResult with list of detected anomalies
        """
        log.info(f"[{self.agent_type}] Running anomaly detection for tenant {self.tenant_id}")

        user_prompt = self.build_user_prompt(
            historical_data=historical_data,
            current_data=current_data,
            baseline_stats=baseline_stats,
        )

        result = self.call_ai(user_prompt)

        if result.success:
            log.info(f"[{self.agent_type}] Detected {len(result.data.get('anomalies', []))} anomalies")
        else:
            log.error(f"[{self.agent_type}] Failed: {result.error}")

        return result
