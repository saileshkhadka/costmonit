"""
Report Generator Agent
======================
Creates executive-ready cost reports.
"""

import json
import logging
from typing import Dict, Any

from .base_agent import BaseAgent, AgentResult
from .prompts import ReporterPrompts

log = logging.getLogger("costmonitor.agents")


class ReporterAgent(BaseAgent):
    """AI agent for generating cost reports."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "reporter")

    def get_system_prompt(self) -> str:
        return ReporterPrompts.SYSTEM

    def build_user_prompt(self, report_type: str, period: str, cost_summary: dict,
                          recommendations: list, anomalies: list) -> str:
        return ReporterPrompts.build_user_prompt(
            report_type, period, cost_summary, recommendations, anomalies
        )

    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON report from Claude."""
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()

        report = json.loads(json_str)
        return report

    def run(self, report_type: str, period: str, cost_summary: dict,
            recommendations: list = None, anomalies: list = None) -> AgentResult:
        """
        Generate an executive cost report.
        
        Args:
            report_type: 'daily' | 'weekly' | 'monthly' | 'custom'
            period: Time period (e.g., "June 1-5, 2026")
            cost_summary: Dict with total, trend, services, regions, etc.
            recommendations: List of top recommendations
            anomalies: List of recent anomalies
            
        Returns:
            AgentResult with formatted report
        """
        if recommendations is None:
            recommendations = []
        if anomalies is None:
            anomalies = []

        log.info(f"[{self.agent_type}] Generating {report_type} report for {period}")

        user_prompt = self.build_user_prompt(
            report_type=report_type,
            period=period,
            cost_summary=cost_summary,
            recommendations=recommendations,
            anomalies=anomalies,
        )

        result = self.call_ai(user_prompt)

        if result.success:
            log.info(f"[{self.agent_type}] Generated report with {len(result.data.get('sections', []))} sections")
        else:
            log.error(f"[{self.agent_type}] Failed: {result.error}")

        return result
