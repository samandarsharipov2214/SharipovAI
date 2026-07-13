from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "audit-results"


@dataclass
class Check:
    phase: int
    area: str
    name: str
    status: str
    severity: str
    evidence: str
    recommendation: str = ""


CHECKS: list[Check] = []


def add(phase: int, area: str, name: str, ok: bool, evidence: str, *, severity: str = "medium", recommendation: str = "") -> None:
    CHECKS.append(Check(phase, area, name, "passed" if ok else "failed", "none" if ok else severity, evidence, recommendation))


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 120) -> tuple[int, str]:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        text = (result.stdout + "\n" + result.stderr).strip()
        return result.returncode, text[-12000:]
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def tracked_files() -> list[Path]:
    code, output = run(["git", "ls-files"])
    if code == 0:
        return [ROOT / line for line in output.splitlines() if line.strip()]
    ignored = {".git", ".venv", "venv", "node_modules", "audit-results", "data", "runtime"}
    return [p for p in ROOT.rglob("*") if p.is_file() and not any(part in ignored for part in p.parts)]


def phase1_architecture() -> None:
    py_files = [p for p in tracked_files() if p.suffix == ".py"]
    syntax_errors: list[str] = []
    for path in py_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            syntax_errors.append(f"{path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
    add(1, "architecture", "python_syntax", not syntax_errors, f"python_files={len(py_files)}; errors={syntax_errors[:20]}", severity="critical", recommendation="Исправить синтаксис до запуска приложения.")

    init_file = ROOT / "dashboard" / "__init__.py"
    init_text = init_file.read_text(encoding="utf-8") if init_file.exists() else ""
    installers = re.findall(r"^install_[A-Za-z0-9_]+\(app\)", init_text, flags=re.M)
    add(1, "architecture", "single_runtime_entrypoint", bool(init_text and installers), f"dashboard/__init__.py installers={len(installers)}", severity="critical", recommendation="Оставить одну каноническую точку сборки FastAPI.")

    duplicate_imports = sorted({x for x in installers if installers.count(x) > 1})
    add(1, "architecture", "duplicate_installers", not duplicate_imports, f"duplicates={duplicate_imports}", severity="high", recommendation="Удалить повторную установку одного API-модуля.")

    old_files = [ROOT / "dashboard/templates/index.html", ROOT / "dashboard/static/mini-app-live.js"]
    remaining = [str(p.relative_to(ROOT)) for p in old_files if p.exists()]
    add(1, "architecture", "old_frontend_removed", not remaining, f"remaining={remaining}", severity="medium", recommendation="Удалить или явно изолировать старый интерфейс.")

    req = ROOT / "requirements.txt"
    req_lines = [line.strip() for line in req.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")] if req.exists() else []
    broad = [line for line in req_lines if ">=" in line or line.endswith("*")]
    add(1, "dependencies", "reproducible_dependencies", not broad, f"dependencies={len(req_lines)}; broad_constraints={broad}", severity="medium", recommendation="Зафиксировать проверенные версии или добавить lock-файл.")

    large = []
    for path in tracked_files():
        try:
            if path.stat().st_size > 500_000:
                large.append(f"{path.relative_to(ROOT)}={path.stat().st_size}")
        except OSError:
            pass
    add(1, "architecture", "oversized_tracked_files", not large, f"large_files={large[:30]}", severity="low", recommendation="Вынести бинарные/генерируемые данные из Git.")


def import_app_routes() -> tuple[list[Any], str]:
    sys.path.insert(0, str(ROOT))
    try:
        import dashboard  # type: ignore
        return list(getattr(dashboard.app, "routes", [])), "ok"
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def phase2_ai_backend() -> None:
    routes, import_state = import_app_routes()
    add(2, "backend", "application_import", bool(routes), import_state, severity="critical", recommendation="Исправить импорт/инициализацию приложения.")
    if not routes:
        return

    seen: dict[tuple[str, str], int] = {}
    api_paths: set[str] = set()
    for route in routes:
        path = str(getattr(route, "path", ""))
        methods = set(getattr(route, "methods", set()) or set())
        if path.startswith("/api/"):
            api_paths.add(path)
        for method in methods:
            key = (method, path)
            seen[key] = seen.get(key, 0) + 1
    duplicates = [f"{m} {p} x{count}" for (m, p), count in seen.items() if count > 1]
    add(2, "backend", "duplicate_routes", not duplicates, f"routes={len(routes)}; api_paths={len(api_paths)}; duplicates={duplicates}", severity="critical", recommendation="Оставить одного владельца каждого method+path.")

    required = {
        "/api/health",
        "/api/run",
        "/api/ai-bots",
        "/api/social-news",
        "/api/exchange/account/snapshot",
        "/api/market/bybit-websocket/status",
        "/api/learning-os/status",
        "/api/evidence-vault/recent",
        "/api/virtual-account/state",
        "/api/ai-control-center/daily-report",
        "/api/system/health",
        "/api/system/recovery-plan",
    }
    missing = sorted(required - api_paths)
    add(2, "backend", "required_api_contract", not missing, f"missing={missing}", severity="critical", recommendation="Восстановить обязательные API-контракты нового сайта.")

    init_text = (ROOT / "dashboard" / "__init__.py").read_text(encoding="utf-8")
    expected_organs = [
        "install_database_api", "install_news_agent_network_api", "install_market_data_api",
        "install_autonomous_trading_api", "install_execution_stages_api", "install_bybit_account_api",
        "install_control_plane_api", "install_ai_organ_state_api", "install_system_health_api",
        "install_system_watchdog",
    ]
    missing_organs = [name for name in expected_organs if name not in init_text]
    add(2, "ai", "core_organs_registered", not missing_organs, f"missing={missing_organs}", severity="critical", recommendation="Подключить отсутствующий канонический орган, не создавая дубль.")

    live_flags = []
    for name in ("EXCHANGE_LIVE_TRADING_ENABLED", "TESTNET_EXECUTION_ENABLED"):
        if os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}:
            live_flags.append(name)
    kill_switch = os.getenv("EXECUTION_KILL_SWITCH", "").strip().lower() in {"1", "true", "yes", "on"}
    add(2, "security", "financial_execution_locked", not live_flags and kill_switch, f"enabled_execution_flags={live_flags}; kill_switch={kill_switch}", severity="critical", recommendation="Отключить исполнение и включить аварийный выключатель до завершения аудита.")


def phase3_infrastructure_static() -> None:
    required = [
        "Dockerfile", "deploy/vps/docker-compose.yml", "deploy/vps/update_from_main.sh",
        "deploy/vps/remote_agent.sh", ".github/workflows/vps-recovery.yml",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    add(3, "infrastructure", "deployment_files", not missing, f"missing={missing}", severity="high", recommendation="Восстановить единый VPS-контур развёртывания.")

    shell_files = [ROOT / "deploy/vps/update_from_main.sh", ROOT / "deploy/vps/remote_agent.sh"]
    bash = shutil.which("bash")
    shell_errors = []
    if bash:
        for path in shell_files:
            if path.exists():
                code, output = run([bash, "-n", str(path)])
                if code:
                    shell_errors.append(f"{path.relative_to(ROOT)}: {output}")
    add(3, "infrastructure", "shell_syntax", not shell_errors, f"errors={shell_errors}", severity="critical", recommendation="Исправить shell-синтаксис до автодеплоя.")

    workflow = ROOT / ".github/workflows/vps-recovery.yml"
    workflow_text = workflow.read_text(encoding="utf-8") if workflow.exists() else ""
    unsafe_markers = [x for x in ["EXCHANGE_LIVE_TRADING_ENABLED=1", "TESTNET_EXECUTION_ENABLED=1", "EXECUTION_KILL_SWITCH=0"] if x in workflow_text]
    add(3, "security", "workflow_does_not_enable_trading", not unsafe_markers, f"unsafe_markers={unsafe_markers}", severity="critical", recommendation="Запретить CI менять торговые флаги.")


def phase4_frontend() -> None:
    index = ROOT / "dashboard/static/web2/index.html"
    text = index.read_text(encoding="utf-8") if index.exists() else ""
    add(4, "frontend", "web2_index_exists", bool(text), "dashboard/static/web2/index.html", severity="critical")
    if not text:
        return

    pages = re.findall(r'data-page="([^"]+)"', text)
    duplicates = sorted({p for p in pages if pages.count(p) > 1})
    add(4, "frontend", "navigation_unique", not duplicates, f"pages={len(pages)}; duplicates={duplicates}", severity="high", recommendation="Оставить одну кнопку на раздел.")

    assets = re.findall(r'(?:src|href)="(/static/web2/[^"]+)"', text)
    missing_assets = []
    for asset in assets:
        clean = asset.split("?", 1)[0].removeprefix("/static/web2/")
        if not (ROOT / "dashboard/static/web2" / clean).exists():
            missing_assets.append(asset)
    add(4, "frontend", "referenced_assets_exist", not missing_assets, f"assets={len(assets)}; missing={missing_assets}", severity="critical", recommendation="Исправить ссылки на отсутствующие JS/CSS.")

    js_files = [ROOT / "dashboard/static/web2" / a.split("?", 1)[0].removeprefix("/static/web2/") for a in assets if a.split("?", 1)[0].endswith(".js")]
    node = shutil.which("node")
    js_errors = []
    if node:
        for path in js_files:
            code, output = run([node, "--check", str(path)])
            if code:
                js_errors.append(f"{path.name}: {output}")
    add(4, "frontend", "javascript_syntax", not js_errors, f"checked={len(js_files) if node else 0}; node_available={bool(node)}; errors={js_errors}", severity="critical", recommendation="Исправить JS-синтаксис.")

    coordinator = ROOT / "dashboard/static/web2/navigation_coordinator_v23.js"
    coordinator_text = coordinator.read_text(encoding="utf-8") if coordinator.exists() else ""
    brittle = "Object.defineProperty(content, 'innerHTML'" in coordinator_text and "new Error().stack" in coordinator_text
    add(4, "frontend", "navigation_without_stack_based_dom_guard", not brittle, "stack_based_innerHTML_guard=" + str(brittle), severity="high", recommendation="Заменить перехват innerHTML на явный единый router/render API.")

    synthetic_patterns = []
    for path in js_files:
        body = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in ("Math.random(", "demoData", "fakeData", "mockData"):
            if pattern in body:
                synthetic_patterns.append(f"{path.name}:{pattern}")
    add(4, "truthfulness", "no_synthetic_runtime_data", not synthetic_patterns, f"matches={synthetic_patterns}", severity="critical", recommendation="Удалить синтетические значения из рабочего интерфейса.")


def safe_json_get(url: str, timeout: float = 8.0) -> tuple[bool, float, Any, str]:
    started = time.perf_counter()
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SharipovAI-Audit/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            latency = (time.perf_counter() - started) * 1000
            data = json.loads(raw.decode("utf-8"))
            return 200 <= response.status < 300, latency, data, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, (time.perf_counter() - started) * 1000, None, f"HTTP {exc.code}"
    except Exception as exc:
        return False, (time.perf_counter() - started) * 1000, None, f"{type(exc).__name__}: {exc}"


def phase3_and_5_live(base: str) -> None:
    endpoints = {
        "health": "/health",
        "api_health": "/api/health",
        "system_health": "/api/system/health",
        "recovery_plan": "/api/system/recovery-plan",
        "market_stream": "/api/market/bybit-websocket/status",
        "account": "/api/exchange/account/snapshot",
        "ai_bots": "/api/ai-bots",
        "decision": "/api/run",
        "news": "/api/social-news",
        "learning": "/api/learning-os/status",
        "evidence": "/api/evidence-vault/recent",
        "virtual": "/api/virtual-account/state",
        "reports": "/api/ai-control-center/daily-report",
    }
    live: dict[str, tuple[bool, float, Any, str]] = {}
    for name, path in endpoints.items():
        live[name] = safe_json_get(base.rstrip("/") + path)
        ok, latency, data, detail = live[name]
        add(5, "live_api", name, ok and isinstance(data, dict), f"{detail}; latency_ms={latency:.1f}; json_object={isinstance(data, dict)}", severity="critical", recommendation=f"Исправить живой маршрут {path}.")

    market = live.get("market_stream", (False, 0, {}, ""))[2] or {}
    verified_market = bool(market.get("verified") is True or market.get("status") in {"connected", "healthy", "ok"})
    add(5, "market", "realtime_market_verified", verified_market, f"status={market.get('status')}; verified={market.get('verified')}", severity="critical", recommendation="Восстановить публичный Bybit WebSocket и свежесть котировок.")

    account = live.get("account", (False, 0, {}, ""))[2] or {}
    account_confirmed = bool(account.get("connected") is True or account.get("verified") is True or account.get("snapshot"))
    add(5, "bybit", "private_account_confirmed", account_confirmed, f"connected={account.get('connected')}; verified={account.get('verified')}; snapshot={bool(account.get('snapshot'))}", severity="high", recommendation="Проверить read-only ключи и права Bybit.")

    bots = live.get("ai_bots", (False, 0, {}, ""))[2] or {}
    bot_items = bots.get("bots") if isinstance(bots.get("bots"), list) else []
    stale = [str(item.get("name") or item.get("id") or "unknown") for item in bot_items if float(item.get("heartbeat_age_seconds", 10**9) or 10**9) > 90]
    add(5, "ai", "ai_heartbeats_fresh", bool(bot_items) and not stale, f"bots={len(bot_items)}; stale={stale}", severity="high", recommendation="Восстановить heartbeat зависших ИИ-модулей.")

    news = live.get("news", (False, 0, {}, ""))[2] or {}
    items = news.get("news")
    if isinstance(items, dict):
        items = items.get("items")
    if not isinstance(items, list):
        items = news.get("items") if isinstance(news.get("items"), list) else []
    add(5, "news", "news_feed_nonempty", bool(items), f"items={len(items)}", severity="high", recommendation="Восстановить источники и обновление News AI.")

    disk = shutil.disk_usage(ROOT)
    disk_used = disk.used / disk.total * 100 if disk.total else 100.0
    add(3, "vps", "disk_capacity", disk_used < 85, f"used_percent={disk_used:.1f}; free_bytes={disk.free}", severity="high", recommendation="Освободить диск и настроить ротацию логов/бэкапов.")

    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    cpu = os.cpu_count() or 1
    add(3, "vps", "load_average", load[0] < cpu * 2, f"load1={load[0]:.2f}; cpu_count={cpu}", severity="medium", recommendation="Найти процесс, создающий перегрузку VPS.")

    listeners = {}
    for port in (80, 443, 8000):
        sock = socket.socket()
        sock.settimeout(0.5)
        try:
            listeners[port] = sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()
    add(3, "vps", "expected_ports", listeners.get(8000, False), f"listeners={listeners}", severity="critical", recommendation="Запустить приложение на 127.0.0.1:8000 и проверить reverse proxy.")

    for service in ("docker", "nginx", "caddy"):
        if shutil.which("systemctl"):
            code, output = run(["systemctl", "is-active", service], timeout=10)
            add(3, "vps", f"service_{service}", code == 0 or service in {"nginx", "caddy"}, f"state={output.strip()}", severity="medium", recommendation=f"Проверить сервис {service}; допустимо использовать только один reverse proxy.")


def secret_scan() -> None:
    patterns = {
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
        "telegram_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
        "generic_secret_assignment": re.compile(r"(?i)(api[_-]?secret|secret[_-]?key|password)\s*=\s*['\"][^'\"]{8,}['\"]"),
    }
    findings: list[str] = []
    allowed_suffixes = {".py", ".js", ".ts", ".json", ".yml", ".yaml", ".env", ".md", ".sh", ".toml", ".ini"}
    for path in tracked_files():
        if path.suffix.lower() not in allowed_suffixes or path.name.endswith(".example"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}:{name}")
    add(5, "security", "no_committed_secrets", not findings, f"findings={findings}", severity="critical", recommendation="Немедленно отозвать найденные секреты и удалить их из истории Git.")


def build_report(mode: str) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "critical": 0, "high": 0, "medium": 0, "low": 0}
    phase_scores: dict[int, dict[str, int]] = {i: {"passed": 0, "total": 0} for i in range(1, 6)}
    for check in CHECKS:
        counts[check.status] += 1
        phase_scores[check.phase]["total"] += 1
        if check.status == "passed":
            phase_scores[check.phase]["passed"] += 1
        elif check.severity in counts:
            counts[check.severity] += 1
    scores = {str(phase): round(v["passed"] / v["total"] * 100) if v["total"] else 0 for phase, v in phase_scores.items()}
    total = len(CHECKS)
    overall = round(counts["passed"] / total * 100) if total else 0
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "overall_percent": overall,
        "phase_percent": scores,
        "counts": counts,
        "checks": [asdict(c) for c in CHECKS],
    }


def write_reports(payload: dict[str, Any], suffix: str) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = RESULTS_DIR / f"audit-{suffix}.json"
    md_path = RESULTS_DIR / f"audit-{suffix}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"# SharipovAI — аудит ({suffix})",
        "",
        f"Дата: `{payload['generated_at']}`",
        f"Общая подтверждённая готовность этой проверки: **{payload['overall_percent']}%**",
        "",
        "## Фазы",
    ]
    phase_names = {1: "Архитектура", 2: "ИИ и backend", 3: "Инфраструктура", 4: "Сайт", 5: "Качество и живая система"}
    for phase in range(1, 6):
        lines.append(f"- Фаза {phase} — {phase_names[phase]}: **{payload['phase_percent'][str(phase)]}%**")
    lines += ["", "## Найденные проблемы"]
    failed = [c for c in payload["checks"] if c["status"] == "failed"]
    if not failed:
        lines.append("- Не обнаружены в границах этой проверки.")
    for item in sorted(failed, key=lambda x: (0 if x["severity"] == "critical" else 1, x["phase"], x["name"])):
        lines += [
            f"### [{item['severity'].upper()}] {item['name']}",
            f"- Фаза: {item['phase']} / {item['area']}",
            f"- Подтверждение: `{item['evidence']}`",
            f"- Исправление: {item['recommendation'] or 'Требуется разбор.'}",
            "",
        ]
    lines += ["## Все проверки", "", "| Фаза | Область | Проверка | Статус | Важность |", "|---:|---|---|---|---|"]
    for item in payload["checks"]:
        lines.append(f"| {item['phase']} | {item['area']} | {item['name']} | {item['status']} | {item['severity']} |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "counts": payload["counts"], "overall_percent": payload["overall_percent"]}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("static", "live", "all"), default="all")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--suffix", default="full")
    args = parser.parse_args()

    if args.mode in {"static", "all"}:
        phase1_architecture()
        phase2_ai_backend()
        phase3_infrastructure_static()
        phase4_frontend()
        secret_scan()
    if args.mode in {"live", "all"}:
        phase3_and_5_live(args.base_url)

    payload = build_report(args.mode)
    write_reports(payload, args.suffix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
