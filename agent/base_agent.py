"""
Base Agent Framework
====================
Abstract base class for all AI agents. Handles:
- API calls to Claude/OpenAI
- Retry logic with exponential backoff
- Token counting and cost tracking
- Caching
- Error handling
"""

import os
import json
import logging
import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, List
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("costmonitor.agents")


@dataclass
class AgentResult:
    """Standard result format for all agents."""
    success: bool
    data: Dict[str, Any]
    tokens_used: int = 0
    cost_usd: float = 0.0
    error: Optional[str] = None
    model: str = ""


class BaseAgent(ABC):
    """Abstract base for all cost monitoring AI agents."""

    def __init__(self, tenant_id: str, agent_type: str):
        self.tenant_id = tenant_id
        self.agent_type = agent_type
        
        # AI configuration
        self.provider = os.getenv("AI_PROVIDER", "claude")
        self.model = os.getenv("AI_MODEL", "claude-3-5-sonnet-20241022")
        self.max_tokens = int(os.getenv("AI_MAX_TOKENS", "2000"))
        self.temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
        
        # Initialize AI client
        if self.provider == "claude":
            from anthropic import Anthropic
            self.client = Anthropic(api_key=os.getenv("CLAUDE_API_KEY"))
        elif self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            raise ValueError(f"Unknown AI provider: {self.provider}")

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the system prompt for this agent."""
        pass

    @abstractmethod
    def build_user_prompt(self, **kwargs) -> str:
        """Build the user message for this agent."""
        pass

    @abstractmethod
    def parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse the AI response into structured data."""
        pass

    def call_ai(self, user_message: str, retries: int = 3) -> AgentResult:
        """Call the AI API with retry logic."""
        attempt = 0
        last_error = None

        while attempt < retries:
            try:
                attempt += 1
                log.info(f"[{self.agent_type}] API call attempt {attempt}/{retries}")

                if self.provider == "claude":
                    result = self._call_claude(user_message)
                else:
                    result = self._call_openai(user_message)

                return result

            except Exception as e:
                last_error = str(e)
                log.warning(f"[{self.agent_type}] Attempt {attempt} failed: {last_error}")
                
                if attempt < retries:
                    wait_time = 2 ** (attempt - 1)
                    log.info(f"[{self.agent_type}] Retrying in {wait_time}s...")
                    import time
                    time.sleep(wait_time)

        log.error(f"[{self.agent_type}] All {retries} attempts failed")
        return AgentResult(
            success=False,
            data={},
            error=last_error,
            model=self.model,
        )

    def _call_claude(self, user_message: str) -> AgentResult:
        """Call Claude API."""
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=self.get_system_prompt(),
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = response.content[0].text
        tokens_used = response.usage.input_tokens + response.usage.output_tokens
        
        # Claude pricing (as of 2024)
        input_cost_per_1m = 3.0  # $3 per 1M input tokens
        output_cost_per_1m = 15.0  # $15 per 1M output tokens
        cost_usd = (
            (response.usage.input_tokens / 1_000_000) * input_cost_per_1m +
            (response.usage.output_tokens / 1_000_000) * output_cost_per_1m
        )

        try:
            parsed_data = self.parse_response(response_text)
        except Exception as e:
            log.error(f"[{self.agent_type}] Failed to parse response: {e}")
            parsed_data = {"raw_response": response_text}

        return AgentResult(
            success=True,
            data=parsed_data,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            model=self.model,
        )

    def _call_openai(self, user_message: str) -> AgentResult:
        """Call OpenAI API."""
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=self.get_system_prompt(),
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = response.choices[0].message.content
        tokens_used = response.usage.prompt_tokens + response.usage.completion_tokens
        
        # OpenAI pricing (as of 2024)
        if "gpt-4o" in self.model:
            input_cost_per_1m = 2.50
            output_cost_per_1m = 10.0
        elif "gpt-4" in self.model:
            input_cost_per_1m = 30.0
            output_cost_per_1m = 60.0
        else:
            input_cost_per_1m = 0.5
            output_cost_per_1m = 1.5
        
        cost_usd = (
            (response.usage.prompt_tokens / 1_000_000) * input_cost_per_1m +
            (response.usage.completion_tokens / 1_000_000) * output_cost_per_1m
        )

        try:
            parsed_data = self.parse_response(response_text)
        except Exception as e:
            log.error(f"[{self.agent_type}] Failed to parse response: {e}")
            parsed_data = {"raw_response": response_text}

        return AgentResult(
            success=True,
            data=parsed_data,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            model=self.model,
        )

    def generate_cache_key(self, **kwargs) -> str:
        """Generate cache key from kwargs."""
        key_str = json.dumps(kwargs, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()

    @abstractmethod
    def run(self, **kwargs) -> AgentResult:
        """Execute the agent. Override in subclasses."""
        pass
