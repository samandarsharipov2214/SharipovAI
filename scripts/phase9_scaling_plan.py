#!/usr/bin/env python3
"""Generate a fail-closed Phase 9 scaling plan from persisted campaign reports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from campaigns.phase9_results import CampaignResultsService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-id", action="append", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    service = CampaignResultsService()
    reports = []
    for campaign_id in args.campaign_id:
        row = service.get_report(campaign_id)
        if row is None:
            parser.error(f"missing Phase 9 report: {campaign_id}")
        reports.append(row)
    plan = service.prepare_scaling(reports, actor=args.actor, reason=args.reason)
    rendered = json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if plan["status"] == "eligible_for_manual_scaling_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
