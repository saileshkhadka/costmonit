"""
Root Cause Analyzer Agent
==========================
Performs deep-dive investigation of cost events.
"""

import json
import logging
from typing import Dict, Any

from .base_agent import BaseAgent, AgentResult
from .prompts import AnalyzerPrompts

log = logging.getLogger("costmonitor.agents")


class AnalyzerAgent(BaseAgent):
    """AI agent for root cause analysis."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "analyzer")

    def get_system_prompt(self) -> str:
        return AnalyzerPrompts.SYSTEM

    def build_user_prompt(self, anomaly: dict, resources: list, timeline: dict,
                          deploy_logs: str = "") -> str:
        return AnalyzerPrompts.build_user_prompt(anomaly, resources, timeline, deploy_logs)

    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON analysis from Claude."""
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()

        analysis = json.loads(json_str)
        return analysis

    def run(self, anomaly: dict, resources: list = None, timeline: dict = None,
            deploy_logs: str = "") -> AgentResult:
        """
        Perform root cause analysis for a cost anomaly.
        
        Args:
            anomaly: The anomaly event to investigate
            resources: Resources that changed around the time of the anomaly
            timeline: Timeline of events
            deploy_logs: Optional deployment/change logs for correlation
            
        Returns:
            AgentResult with probable cause and evidence
        """
        if resources is None:
            resources = []
        if timeline is None:
            timeline = {}

        log.info(f"[{self.agent_type}] Analyzing anomaly for tenant {self.tenant_id}")

        user_prompt = self.build_user_prompt(
            anomaly=anomaly,
            resources=resources,
            timeline=timeline,
            deploy_logs=deploy_logs,
        )

        result = self.call_ai(user_prompt)

        if result.success:
            analysis = result.data
            confidence = analysis.get("confidence", 0)
            log.info(f"[{self.agent_type}] Analysis complete (confidence: {confidence:.2f})")
        else:
            log.error(f"[{self.agent_type}] Failed: {result.error}")

        return result
