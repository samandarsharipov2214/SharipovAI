from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "audit-results"


@dataclass
class Check:
    phase: int
    name: str
    passed: bool
    severity: str
    evidence: str


checks: list[Check] = []


def add(phase: int, name: str, passed: bool, evidence: str, severity: str = "high") -> None:
    checks.append(Check(phase, name, passed, "none" if passed else severity, evidence))


def run(args: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()[-16000:]
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def tracked() -> list[Path]:
    code, text = run(["git", "ls-files"])
    return [ROOT / line for line in text.splitlines() if line.strip()] if code == 0 else []


def static_audit() -> None:
    files = tracked()
    py = [p for p in files if p.suffix == ".py" and p.exists()]
    syntax = []
    for path in py:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            syntax.append(f"{path.relative_to(ROOT)}:{exc}")
    add(1, "python_syntax", not syntax, f"python_files={len(py)}; errors={syntax[:20]}", "critical")

    code, output = run(["python", "-c", "import dashboard; print(len(dashboard.app.routes))"], 60)
    add(1, "dashboard_import", code == 0, output[-1000:], "critical")

    req = ROOT / "requirements.txt"
    lines = [x.strip() for x in req.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")] if req.exists() else []
    broad = [x for x in lines if ">=" in x or "~=" in x or "*" in x]
    add(1, "dependencies_pinned", not broad, f"broad={broad}", "medium")

    required = ["Dockerfile", "deploy/vps/docker-compose.yml", "deploy/vps/Caddyfile", ".github/workflows/vps-recovery.yml"]
    missing = [x for x in required if not (ROOT / x).exists()]
    add(3, "vps_files", not missing, f"missing={missing}", "critical")

    compose = (ROOT / "deploy/vps/docker-compose.yml").read_text(encoding="utf-8") if (ROOT / "deploy/vps/docker-compose.yml").exists() else ""
    safe = all(token in compose for token in ('EXCHANGE_LIVE_TRADING_ENABLED: "0"', 'EXECUTION_KILL_SWITCH: "1"', '127.0.0.1:8000:8000', 'healthcheck:'))
    add(3, "vps_safety_contract", safe, f"safe={safe}", "critical")

    index = ROOT / "dashboard/static/web2/index.html"
    html = index.read_text(encoding="utf-8") if index.exists() else ""
    add(4, "web2_exists", bool(html), str(index), "critical")
    assets = re.findall(r'(?:src|href)="(/static/web2/[^"]+)"', html)
    missing_assets = []
    js = []
    for asset in assets:
        path = ROOT / "dashboard/static/web2" / asset.split("?", 1)[0].removeprefix("/static/web2/")
        if not path.exists():
            missing_assets.append(asset)
        elif path.suffix == ".js":
            js.append(path)
    add(4, "web2_assets", not missing_assets, f"assets={len(assets)}; missing={missing_assets}", "critical")

    node = shutil.which("node")
    js_errors = []
    if node:
        for path in js:
            code, output = run([node, "--check", str(path)])
            if code:
                js_errors.append(f"{path.name}:{output[-500:]}")
    add(4, "javascript_syntax", bool(node) and not js_errors, f"node={bool(node)}; errors={js_errors}", "critical")

    synthetic = []
    for path in js:
        body = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("Math.random(", "mockData", "fakeData", "demoData"):
            if token in body:
                synthetic.append(f"{path.name}:{token}")
    add(4, "no_runtime_fake_data", not synthetic, f"matches={synthetic}", "critical")

    secret_patterns = [re.compile(r"-----BEGIN .*PRIVATE KEY-----"), re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"), re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")]
    secrets_found = []
    for path in files:
        if not path.exists() or path.suffix.lower() not in {".py", ".js", ".json", ".yml", ".yaml", ".sh", ".md", ".env"} or path.name.endswith(".example"):
            continue
        body = path.read_text(encoding="utf-8", errors="ignore")
        if any(pattern.search(body) for pattern in secret_patterns):
            secrets_found.append(str(path.relative_to(ROOT)))
    add(5, "no_committed_secrets", not secrets_found, f"files={secrets_found}", "critical")


def get_json(base: str, path: str) -> tuple[bool, int, Any, str]:
    try:
        req = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "application/json", "User-Agent": "SharipovAI-Audit-v2"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read(2_000_000).decode("utf-8"))
            return 200 <= response.status < 300, response.status, data, "ok"
    except urllib.error.HTTPError as exc:
        return False, exc.code, None, f"HTTP {exc.code}"
    except Exception as exc:
        return False, 0, None, f"{type(exc).__name__}: {exc}"


def live_audit(base: str) -> None:
    endpoints = {
        "health": "/health",
        "api_health": "/api/health",
        "system_health": "/api/system/health",
        "market_ws": "/api/market/bybit-websocket/status",
        "btc_quote": "/api/market/quote/BTCUSDT",
        "account": "/api/exchange/account/snapshot",
        "bots": "/api/ai-bots",
        "news": "/api/social-news",
        "evidence": "/api/evidence-vault/recent",
        "virtual": "/api/virtual-account/state",
        "reports": "/api/ai-control-center/daily-report",
    }
    payloads: dict[str, Any] = {}
    for name, path in endpoints.items():
        ok, status, data, detail = get_json(base, path)
        payloads[name] = data if isinstance(data, dict) else {}
        add(5, f"live_{name}", ok and isinstance(data, dict), f"status={status}; detail={detail}", "critical")

    market = payloads.get("market_ws", {})
    market_ok = market.get("verified") is True or str(market.get("status", "")).lower() in {"ok", "healthy", "connected", "running"}
    add(2, "market_stream_verified", market_ok, json.dumps(market, ensure_ascii=False)[:1000], "critical")

    bots = payloads.get("bots", {}).get("bots") or payloads.get("bots", {}).get("items") or []
    stale = []
    for bot in bots if isinstance(bots, list) else []:
        try:
            if float(bot.get("heartbeat_age_seconds", 10**9)) > 90:
                stale.append(bot.get("name") or bot.get("id"))
        except Exception:
            stale.append(bot.get("name") or bot.get("id"))
    add(2, "ai_heartbeats", bool(bots) and not stale, f"bots={len(bots) if isinstance(bots, list) else 0}; stale={stale}", "high")

    disk = shutil.disk_usage("/")
    used = disk.used / disk.total * 100 if disk.total else 100
    add(3, "disk_below_85", used < 85, f"used_percent={used:.1f}", "high")
    ports = {}
    for port in (80, 443, 8000):
        sock = socket.socket(); sock.settimeout(0.5)
        try: ports[port] = sock.connect_ex(("127.0.0.1", port)) == 0
        finally: sock.close()
    add(3, "ports_80_443_8000", all(ports.values()), f"ports={ports}", "critical")


def write_report(mode: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    failed = [x for x in checks if not x.passed]
    overall = round(sum(x.passed for x in checks) / len(checks) * 100) if checks else 0
    phases = {}
    for phase in range(1, 6):
        rows = [x for x in checks if x.phase == phase]
        phases[str(phase)] = round(sum(x.passed for x in rows) / len(rows) * 100) if rows else None
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "mode": mode, "overall_percent": overall, "phase_percent": phases, "failed": len(failed), "checks": [asdict(x) for x in checks]}
    (OUT / f"audit-v2-{mode}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# SharipovAI audit v2 ({mode})", "", f"Overall: **{overall}%**", f"Failed: **{len(failed)}**", "", "## Phases"]
    for phase, score in phases.items(): lines.append(f"- Phase {phase}: {score if score is not None else 'n/a'}%")
    lines += ["", "## Failed checks"]
    for item in failed:
        lines += [f"### [{item.severity.upper()}] {item.name}", f"- Evidence: `{item.evidence}`", ""]
    (OUT / f"audit-v2-{mode}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"overall_percent": overall, "failed": len(failed), "phases": phases}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("static", "live", "all"), default="all")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if args.mode in {"static", "all"}: static_audit()
    if args.mode in {"live", "all"}: live_audit(args.base_url)
    write_report(args.mode)
    return 1 if any(not x.passed and x.severity == "critical" for x in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
