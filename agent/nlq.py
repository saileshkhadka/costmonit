"""
Natural Language Query Agent
=============================
Answers cost questions in plain English.
"""

import json
import logging
from typing import Dict, Any

from .base_agent import BaseAgent, AgentResult
from .prompts import NLQPrompts

log = logging.getLogger("costmonitor.agents")


class NLQAgent(BaseAgent):
    """AI agent for natural language cost queries."""

    def __init__(self, tenant_id: str):
        super().__init__(tenant_id, "nlq")

    def get_system_prompt(self) -> str:
        return NLQPrompts.SYSTEM

    def build_user_prompt(self, question: str, cost_data: dict, metadata: dict) -> str:
        return NLQPrompts.build_user_prompt(question, cost_data, metadata)

    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse JSON response from Claude."""
        if "```json" in response_text:
            json_str = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            json_str = response_text.split("```")[1].split("```")[0].strip()
        else:
            json_str = response_text.strip()

        response = json.loads(json_str)
        return response

    def run(self, question: str, cost_data: dict, metadata: dict = None) -> AgentResult:
        """
        Answer a natural language question about costs.
        
        Args:
            question: User's question (e.g., "How much did I spend on EC2 last month?")
            cost_data: Relevant cost data for answering the question
            metadata: Additional context (date ranges, services, regions, etc.)
            
        Returns:
            AgentResult with natural language answer and data
        """
        log.info(f"[{self.agent_type}] Processing query for tenant {self.tenant_id}: {question[:50]}...")

        if metadata is None:
            metadata = {}

        user_prompt = self.build_user_prompt(question, cost_data, metadata)

        result = self.call_ai(user_prompt)

        if result.success:
            log.info(f"[{self.agent_type}] Generated answer (confidence: {result.data.get('confidence', 0):.2f})")
        else:
            log.error(f"[{self.agent_type}] Failed: {result.error}")

        return result
