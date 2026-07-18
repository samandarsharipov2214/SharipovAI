#!/usr/bin/env python3
"""Generate and print canonical Phase 8 analysis for a completed campaign."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from campaigns import TestnetShadowCampaign
from campaigns.phase7_monitor import Phase7CampaignMonitor
from campaigns.phase8_analysis import PostCampaignAnalysisService
from storage import ProjectDatabase


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    database = ProjectDatabase()
    campaign_service = TestnetShadowCampaign(database)
    campaign = campaign_service.get(args.campaign_id)
    if campaign is None:
        print(json.dumps({"status": "blocked", "error": "campaign not found"}), file=sys.stderr)
        return 2
    if str(campaign.get("status") or "") != "completed":
        print(json.dumps({"status": "blocked", "error": "campaign is not completed"}), file=sys.stderr)
        return 2
    monitor = Phase7CampaignMonitor(database, campaign=campaign_service)
    analysis = PostCampaignAnalysisService(database).analyze(campaign, monitor.actual_fills(args.campaign_id))
    rendered = json.dumps(analysis, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if not analysis["failed_gates"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
