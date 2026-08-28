"""
Database helpers for agent operations.
======================================
Functions to store agent runs, recommendations, anomalies, etc. in Postgres.
"""

import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import psycopg2
import psycopg2.extras

log = logging.getLogger("costmonitor.db")


class AgentDatabase:
    """Helper for storing agent results in Postgres."""

    def __init__(self, db_url: str):
        self.db_url = db_url

    def get_connection(self):
        """Get a database connection."""
        return psycopg2.connect(self.db_url, cursor_factory=psycopg2.extras.RealDictCursor)

    def save_agent_run(self, tenant_id: str, agent_type: str, trigger_type: str,
                       status: str, input_data: dict, output_data: dict = None,
                       error_message: str = None, tokens_used: int = 0,
                       cost_usd: float = 0.0, api_model: str = "") -> str:
        """Save an agent run to the database."""
        run_id = str(uuid.uuid4())
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO agent_runs 
                        (id, tenant_id, agent_type, trigger_type, status, input_data, 
                         output_data, error_message, tokens_used, cost_usd, api_model, completed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        run_id, tenant_id, agent_type, trigger_type, status,
                        json.dumps(input_data), json.dumps(output_data or {}),
                        error_message, tokens_used, cost_usd, api_model,
                        datetime.now(timezone.utc) if status != 'pending' else None
                    ))
                conn.commit()
            log.info(f"Saved agent run {run_id} ({agent_type}, status={status})")
            return run_id
        except Exception as e:
            log.error(f"Failed to save agent run: {e}")
            raise

    def save_recommendations(self, tenant_id: str, aws_account_id: str, 
                            agent_type: str, recommendations: list) -> int:
        """Save recommendations to the database."""
        saved_count = 0
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for rec in recommendations:
                        rec_id = str(uuid.uuid4())
                        cur.execute("""
                            INSERT INTO ai_recommendations
                            (id, tenant_id, aws_account_id, agent_type, recommendation_type,
                             title, description, priority, estimated_savings_usd,
                             confidence_score, action_steps, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                        """, (
                            rec_id, tenant_id, aws_account_id, agent_type,
                            rec.get('recommendation_type', 'other'),
                            rec.get('title', ''),
                            rec.get('description', ''),
                            rec.get('priority', 'medium'),
                            rec.get('estimated_savings_monthly_usd', 0),
                            rec.get('confidence_score', 0),
                            json.dumps(rec.get('action_steps', []))
                        ))
                        saved_count += 1
                conn.commit()
            log.info(f"Saved {saved_count} recommendations for tenant {tenant_id}")
        except Exception as e:
            log.error(f"Failed to save recommendations: {e}")
            raise
        
        return saved_count

    def save_anomalies(self, tenant_id: str, aws_account_id: str, anomalies: list) -> int:
        """Save detected anomalies to the database."""
        saved_count = 0
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for anomaly in anomalies:
                        anomaly_id = str(uuid.uuid4())
                        cur.execute("""
                            INSERT INTO anomaly_events
                            (id, tenant_id, aws_account_id, anomaly_type, severity,
                             service, region, current_value, baseline_value, percent_change,
                             description, suspected_cause, state)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'firing')
                        """, (
                            anomaly_id, tenant_id, aws_account_id,
                            anomaly.get('anomaly_type', 'unknown'),
                            anomaly.get('severity', 'warning'),
                            anomaly.get('service'),
                            anomaly.get('region'),
                            anomaly.get('current_value'),
                            anomaly.get('baseline_value'),
                            anomaly.get('percent_change', 0),
                            anomaly.get('description', ''),
                            anomaly.get('suspected_cause', ''),
                        ))
                        saved_count += 1
                conn.commit()
            log.info(f"Saved {saved_count} anomalies for tenant {tenant_id}")
        except Exception as e:
            log.error(f"Failed to save anomalies: {e}")
            raise
        
        return saved_count

    def get_active_budgets(self, tenant_id: str, aws_account_id: Optional[str] = None) -> list:
        """Fetch active budgets that apply to a tenant and optional account."""
        account_filter = "AND (aws_account_id = %s OR aws_account_id IS NULL)" if aws_account_id else ""
        params = [tenant_id]
        if aws_account_id:
            params.append(aws_account_id)

        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""SELECT id, name, aws_account_id, service_group, region,
                                   limit_usd, period, alert_at_pct
                            FROM budgets
                            WHERE tenant_id = %s AND is_active = true {account_filter}""",
                        params,
                    )
                    return [dict(budget) for budget in cur.fetchall()]
        except Exception as e:
            log.error(f"Failed to get active budgets: {e}")
            return []

    def save_alert_events(self, tenant_id: str, alerts: list) -> int:
        """Persist newly triggered budget alerts without duplicating active alerts."""
        saved_count = 0
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    for alert in alerts:
                        cur.execute(
                            """INSERT INTO alert_events
                                       (tenant_id, budget_id, aws_account_id, alert_type,
                                        severity, title, message, current_value,
                                        threshold_value, percent_used, state)
                                SELECT %s, %s, %s, 'budget_threshold', %s, %s, %s, %s, %s, %s, 'firing'
                                WHERE NOT EXISTS (
                                    SELECT 1 FROM alert_events
                                    WHERE tenant_id = %s AND budget_id = %s AND state = 'firing'
                                )""",
                            (
                                tenant_id,
                                alert["budget_id"],
                                alert.get("aws_account_id"),
                                alert["severity"],
                                f"Budget threshold: {alert['budget_name']}",
                                alert["message"],
                                alert["current_usd"],
                                alert["limit_usd"],
                                alert["percent_used"],
                                tenant_id,
                                alert["budget_id"],
                            ),
                        )
                        saved_count += cur.rowcount
                conn.commit()
        except Exception as e:
            log.error(f"Failed to save alert events: {e}")
            raise
        return saved_count

    def save_forecast(self, tenant_id: str, aws_account_id: str, forecast: dict) -> str:
        """Save a spending forecast to the database."""
        forecast_id = str(uuid.uuid4())
        
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO forecast_records
                        (id, tenant_id, aws_account_id, forecast_period, forecast_date,
                         forecasted_cost_usd, confidence_level, method, budget_limit,
                         budget_breach_probability, days_to_breach, notes)
                        VALUES (%s, %s, %s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        forecast_id, tenant_id, aws_account_id,
                        forecast.get('forecast_period', 'monthly'),
                        forecast.get('projected_month_end_usd', 0),
                        forecast.get('confidence_level', 0),
                        forecast.get('method', 'linear'),
                        forecast.get('budget_limit'),
                        forecast.get('budget_breach_probability', 0),
                        forecast.get('days_to_breach'),
                        forecast.get('notes', '')
                    ))
                conn.commit()
            log.info(f"Saved forecast {forecast_id}")
            return forecast_id
        except Exception as e:
            log.error(f"Failed to save forecast: {e}")
            raise

    def get_cost_data(self, tenant_id: str, aws_account_id: Optional[str], days: int = 30) -> dict:
        """Fetch recent cost data for analysis."""
        try:
            account_filter = ""
            params = [tenant_id, f"{days} days"]
            if aws_account_id:
                account_filter = "AND aws_account_id = %s"
                params.insert(1, aws_account_id)

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get cost by service
                    cur.execute(f"""
                        SELECT service, service_group, SUM(cost_usd) as total
                        FROM cost_records
                        WHERE tenant_id = %s {account_filter}
                        AND granularity = 'DAILY'
                        AND date >= CURRENT_DATE - %s::interval
                        GROUP BY service, service_group
                        ORDER BY total DESC
                        LIMIT 20
                    """, params)
                    services = cur.fetchall()

                    # Get the complete total independently of the top-service limit.
                    cur.execute(f"""
                        SELECT COALESCE(SUM(cost_usd), 0) AS total
                        FROM cost_records
                        WHERE tenant_id = %s {account_filter}
                        AND granularity = 'DAILY'
                        AND date >= CURRENT_DATE - %s::interval
                    """, params)
                    total = cur.fetchone() or {}

                    # Get regional totals for the monitoring overview.
                    cur.execute(f"""
                        SELECT region, SUM(cost_usd) AS total
                        FROM cost_records
                        WHERE tenant_id = %s {account_filter}
                        AND granularity = 'DAILY'
                        AND date >= CURRENT_DATE - %s::interval
                        GROUP BY region
                        ORDER BY total DESC
                        LIMIT 20
                    """, params)
                    regions = cur.fetchall()

                    # Get daily totals
                    cur.execute(f"""
                        SELECT date, SUM(cost_usd) as total
                        FROM cost_records
                        WHERE tenant_id = %s {account_filter}
                        AND granularity = 'DAILY'
                        AND date >= CURRENT_DATE - %s::interval
                        GROUP BY date
                        ORDER BY date DESC
                    """, params)
                    daily = cur.fetchall()

                    return {
                        "by_service": [dict(s) for s in services],
                        "by_region": [dict(r) for r in regions],
                        "daily": [dict(d) for d in daily],
                        "total": float(total.get("total") or 0.0),
                        "period_days": days
                    }
        except Exception as e:
            log.error(f"Failed to get cost data: {e}")
            return {"error": str(e)}

    def get_idle_resources(self, tenant_id: str, aws_account_id: Optional[str]) -> list:
        """Fetch idle resources for analysis."""
        try:
            account_filter = ""
            params = [tenant_id]
            if aws_account_id:
                account_filter = "AND aws_account_id = %s"
                params.append(aws_account_id)

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT resource_id, resource_type, name, monthly_cost_usd,
                               cpu_avg_pct, memory_avg_pct, state
                        FROM resource_inventory
                        WHERE tenant_id = %s {account_filter}
                        AND is_idle = true
                        ORDER BY monthly_cost_usd DESC
                        LIMIT 20
                    """, params)
                    idle = cur.fetchall()
                    return [dict(r) for r in idle]
        except Exception as e:
            log.error(f"Failed to get idle resources: {e}")
            return []

    def get_resource_inventory_summary(self, tenant_id: str, aws_account_id: Optional[str]) -> dict:
        """Fetch a summary of resource inventory for analysis."""
        try:
            account_filter = ""
            params = [tenant_id]
            if aws_account_id:
                account_filter = "AND aws_account_id = %s"
                params.append(aws_account_id)

            with self.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"""
                        SELECT COUNT(*) AS total_resources,
                               SUM(COALESCE(monthly_cost_usd, 0)) AS total_monthly_cost,
                               COUNT(*) FILTER (WHERE is_idle) AS idle_resources
                        FROM resource_inventory
                        WHERE tenant_id = %s {account_filter}
                    """, params)
                    summary = cur.fetchone() or {}

                    cur.execute(f"""
                        SELECT resource_type, COUNT(*) AS count,
                               SUM(COALESCE(monthly_cost_usd, 0)) AS monthly_cost_usd
                        FROM resource_inventory
                        WHERE tenant_id = %s {account_filter}
                        GROUP BY resource_type
                        ORDER BY monthly_cost_usd DESC
                        LIMIT 20
                    """, params)
                    by_type = cur.fetchall()

                    cur.execute(f"""
                        SELECT service_group, COUNT(*) AS count,
                               SUM(COALESCE(monthly_cost_usd, 0)) AS monthly_cost_usd
                        FROM resource_inventory
                        WHERE tenant_id = %s {account_filter}
                        GROUP BY service_group
                        ORDER BY monthly_cost_usd DESC
                    """, params)
                    by_service_group = cur.fetchall()

                    return {
                        "total_resources": int(summary.get("total_resources") or 0),
                        "total_monthly_cost_usd": float(summary.get("total_monthly_cost") or 0.0),
                        "idle_resources": int(summary.get("idle_resources") or 0),
                        "resources_by_type": [dict(r) for r in by_type],
                        "resources_by_service_group": [dict(r) for r in by_service_group],
                    }
        except Exception as e:
            log.error(f"Failed to get resource inventory summary: {e}")
            return {
                "total_resources": 0,
                "total_monthly_cost_usd": 0.0,
                "idle_resources": 0,
                "resources_by_type": [],
                "resources_by_service_group": [],
            }
