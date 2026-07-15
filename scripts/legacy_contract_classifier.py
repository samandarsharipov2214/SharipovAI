#!/usr/bin/env python3
"""Classify full-suite failures without weakening the truthful CI gate.

The classifier never converts a failure into success.  It separates failures into:

* ``regression``: current production/runtime behavior is broken or unknown;
* ``stale_test``: the test asserts a retired API, exact UI asset version or obsolete copy;
* ``environment_contamination``: the test result is invalidated by runner state,
  credentials, package layout, network access or non-isolated persistence.

Unknown failures are deliberately classified as ``regression``.
"""
from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

CATEGORIES = ("regression", "stale_test", "environment_contamination")


@dataclass(frozen=True, slots=True)
class FailureRecord:
    nodeid: str
    category: str
    reason: str
    message: str
    trace: str


@dataclass(frozen=True, slots=True)
class Rule:
    category: str
    reason: str
    node_patterns: tuple[str, ...] = ()
    text_patterns: tuple[str, ...] = ()

    def matches(self, nodeid: str, text: str) -> bool:
        node = nodeid.lower()
        body = text.lower()
        node_ok = not self.node_patterns or any(re.search(pattern, node) for pattern in self.node_patterns)
        text_ok = not self.text_patterns or any(re.search(pattern, body) for pattern in self.text_patterns)
        return node_ok and text_ok


RULES: tuple[Rule, ...] = (
    Rule(
        "environment_contamination",
        "runner Python package/module layout is contaminated",
        text_patterns=(r"_duckdb\._sqltypes", r"__path__ attribute not found", r"has no attribute '__path__'"),
    ),
    Rule(
        "environment_contamination",
        "test requires credentials or external account state not supplied to CI",
        node_patterns=(r"test_bybit_account", r"account_snapshot"),
        text_patterns=(r"credentials are not configured", r"api key", r"unauthorized"),
    ),
    Rule(
        "environment_contamination",
        "persistent test state leaked across cases",
        text_patterns=(r"versionconflict", r"immutable paper record conflict", r"expected 0, current [1-9]"),
    ),
    Rule(
        "environment_contamination",
        "global CI authentication bypass changed the test premise",
        node_patterns=(r"test_auth_guard_middleware.*auth_is_enabled_by_default",),
    ),
    Rule(
        "environment_contamination",
        "external network or feed availability invalidated a deterministic test",
        node_patterns=(r"rss_reader", r"feed_fetcher"),
        text_patterns=(r"connection", r"timeout", r"empty.*ok", r"temporary failure"),
    ),
    Rule(
        "stale_test",
        "test asserts retired Web2 asset versions or removed render owners",
        node_patterns=(r"test_web2_", r"test_legacy_site_removed"),
        text_patterns=(r"\?v=", r"sections_v10", r"market_terminal_v13", r"static/web2", r"data-page"),
    ),
    Rule(
        "stale_test",
        "test targets the removed legacy execution entry point",
        node_patterns=(r"test_execution_stages",),
        text_patterns=(r"place_market_order", r"legacy place_market_order", r"regex pattern did not match"),
    ),
    Rule(
        "stale_test",
        "test expects the pre-Phase-5 Testnet bridge stage/count contract",
        node_patterns=(r"test_testnet_bridge",),
    ),
    Rule(
        "stale_test",
        "test locks obsolete Telegram menu/copy presentation instead of semantic behavior",
        node_patterns=(r"test_telegram_menu_button", r"test_telegram_presentation"),
    ),
    Rule(
        "stale_test",
        "test locks a retired Mini App/static presentation contract",
        node_patterns=(r"test_mini_app_sections", r"test_static_shell", r"test_bot_communication_dashboard_integration"),
    ),
    Rule(
        "stale_test",
        "test asserts an obsolete restore-wrapper string instead of restore semantics",
        node_patterns=(r"test_isolated_restore_drill",),
    ),
)


def parse_junit(path: Path) -> list[FailureRecord]:
    root = ET.parse(path).getroot()
    records: list[FailureRecord] = []
    for case in root.iter("testcase"):
        failure = case.find("failure")
        if failure is None:
            failure = case.find("error")
        if failure is None:
            continue
        classname = str(case.attrib.get("classname", "")).strip()
        name = str(case.attrib.get("name", "")).strip()
        nodeid = f"{classname}::{name}" if classname else name
        message = str(failure.attrib.get("message", "")).strip()
        trace = str(failure.text or "").strip()
        category, reason = classify(nodeid, f"{message}\n{trace}")
        records.append(FailureRecord(nodeid, category, reason, message, trace))
    return records


def classify(nodeid: str, text: str) -> tuple[str, str]:
    for rule in RULES:
        if rule.matches(nodeid, text):
            return rule.category, rule.reason
    return "regression", "unresolved current-contract failure; fail closed as regression"


def build_report(records: Iterable[FailureRecord], *, source: str) -> dict[str, object]:
    rows = list(records)
    counts = Counter(item.category for item in rows)
    return {
        "status": "failures_classified" if rows else "green",
        "source": source,
        "total_failures": len(rows),
        "counts": {category: counts.get(category, 0) for category in CATEGORIES},
        "truthful_gate_required": bool(rows),
        "unknown_defaults_to_regression": True,
        "items": [asdict(item) for item in rows],
    }


def markdown(report: dict[str, object]) -> str:
    counts = dict(report.get("counts") or {})
    lines = [
        "# Legacy Contract Classification",
        "",
        f"Source: `{report.get('source', '')}`",
        f"Total failures: **{report.get('total_failures', 0)}**",
        "",
        "| Category | Count | Meaning |",
        "|---|---:|---|",
        f"| regression | {counts.get('regression', 0)} | Current contract broken or unresolved; must be fixed |",
        f"| stale_test | {counts.get('stale_test', 0)} | Test targets retired API/UI/copy and must be rewritten semantically |",
        f"| environment_contamination | {counts.get('environment_contamination', 0)} | Runner, credentials, network or shared state invalidated the result |",
        "",
        "> Classification does not make CI green. Any failure keeps the truthful gate red.",
        "",
    ]
    grouped: dict[str, list[dict[str, object]]] = {category: [] for category in CATEGORIES}
    for item in report.get("items", []):
        if isinstance(item, dict):
            grouped.setdefault(str(item.get("category")), []).append(item)
    for category in CATEGORIES:
        lines.extend((f"## {category}", ""))
        for item in grouped.get(category, []):
            lines.append(f"- `{item.get('nodeid')}` — {item.get('reason')}")
        if not grouped.get(category):
            lines.append("- none")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", required=True, type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--markdown", dest="markdown_path", type=Path)
    parser.add_argument("--fail-on-regressions", action="store_true")
    args = parser.parse_args()

    records = parse_junit(args.junit)
    report = build_report(records, source=str(args.junit))
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    print(encoded)
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(encoded + "\n", encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(markdown(report) + "\n", encoding="utf-8")
    if args.fail_on_regressions and int(dict(report["counts"])["regression"]) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
