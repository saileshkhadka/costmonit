"""
analysis.py — AI analysis orchestrator
=====================================
Lightweight scaffolding to run anomaly detection, forecasting and optimizer agents
from the codebase. This module is intentionally small so you can extend it later.

Usage:
    from analysis import run_agent
    run_agent("optimizer", tenant_id, payload)

"""
import logging
from typing import Any, Dict

from agent import (
    OptimizerAgent, AnomalyAgent, ForecasterAgent,
    NLQAgent, ReporterAgent, AnalyzerAgent,
)

log = logging.getLogger("costmonitor.analysis")


AGENT_MAP = {
    "optimizer": OptimizerAgent,
    "anomaly": AnomalyAgent,
    "forecaster": ForecasterAgent,
    "nlq": NLQAgent,
    "reporter": ReporterAgent,
    "analyzer": AnalyzerAgent,
}


def run_agent(agent_type: str, tenant_id: str, payload: Dict[str, Any]):
    """Create and run an agent by type.

    This thin wrapper normalizes inputs and returns the AgentResult object.
    """
    agent_type = agent_type.lower()
    AgentCls = AGENT_MAP.get(agent_type)
    if not AgentCls:
        raise ValueError(f"Unknown agent type: {agent_type}")

    agent = AgentCls(tenant_id=tenant_id)

    # Most agents accept varying kwargs; simply forward the payload dict.
    if not isinstance(payload, dict):
        payload = {}

    log.info(f"Running agent {agent_type} for tenant {tenant_id}")
    return agent.run(**payload)
