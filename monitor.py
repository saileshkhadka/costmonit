"""
External CLI for CloudCostMonitor.

Use this script to fetch AWS cost insights and AI recommendations
from the command line.
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(__file__))

from utils.monitoring import run_monitoring_insights


def parse_args():
    parser = argparse.ArgumentParser(description="AWS Cost Monitoring CLI")
    parser.add_argument("--aws-account-id", dest="aws_account_id", help="AWS account ID to inspect")
    parser.add_argument("--days", type=int, default=30, help="Lookback window in days")
    parser.add_argument("--save-recs", action="store_true", help="Save AI recommendations to the database")
    return parser.parse_args()


def main():
    args = parse_args()

    db_url = os.getenv("DB_URL")
    if not db_url:
        raise SystemExit("Error: DB_URL is required in environment")

    tenant_id = os.getenv("TENANT_ID")
    if not tenant_id:
        raise SystemExit("Error: TENANT_ID is required in environment")

    result = run_monitoring_insights(
        tenant_id=tenant_id,
        db_url=db_url,
        aws_account_id=args.aws_account_id,
        days=args.days,
        save_recommendations=args.save_recs,
    )

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
