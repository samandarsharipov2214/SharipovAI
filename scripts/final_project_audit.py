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
OUT = ROOT / "audit-results"
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}


@dataclass(frozen=True, slots=True)
class Check:
    phase: int
    area: str
    name: str
    passed: bool
    severity: str
    evidence: str
    fix: str = ""


checks: list[Check] = []


def add(phase: int, area: str, name: str, passed: bool, evidence: str, severity: str = "medium", fix: str = "") -> None:
    checks.append(Check(phase, area, name, passed, "none" if passed else severity, evidence, fix))


def command(args: list[str], timeout: int = 120) -> tuple[int, str]:
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout + "\n" + result.stderr).strip()[-20000:]
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def tracked_files() -> list[Path]:
    code, output = command(["git", "ls-files"])
    if code != 0:
        return []
    return [ROOT / item for item in output.splitlines() if item and (ROOT / item).is_file()]


def static_phase_1() -> None:
    files = tracked_files()
    python_files = [path for path in files if path.suffix == ".py"]
    failures: list[str] = []
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            failures.append(f"{path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")
    add(1, "architecture", "python_syntax", not failures, f"python_files={len(python_files)}; errors={failures[:20]}", "critical", "Исправить синтаксис Python.")

    old = [path for path in (ROOT / "dashboard/templates/index.html", ROOT / "dashboard/static/mini-app-live.js") if path.exists()]
    add(1, "architecture", "old_site_removed", not old, f"remaining={[str(path.relative_to(ROOT)) for path in old]}", "medium", "Удалить остатки старого интерфейса.")

    oversized = []
    for path in files:
        try:
            if path.stat().st_size > 1_000_000 and "data/" not in path.relative_to(ROOT).as_posix():
                oversized.append(f"{path.relative_to(ROOT)}={path.stat().st_size}")
        except OSError:
            pass
    add(1, "architecture", "no_oversized_source_files", not oversized, f"oversized={oversized[:20]}", "low", "Вынести большие генерируемые файлы из Git.")

    requirements = ROOT / "requirements.txt"
    lines = [line.strip() for line in requirements.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")] if requirements.exists() else []
    broad = [line for line in lines if ">=" in line or "~=" in line or "*" in line]
    add(1, "dependencies", "reproducible_dependencies", not broad, f"dependencies={len(lines)}; broad={broad}", "medium", "Зафиксировать проверенные версии или lock-файл.")


def static_phase_2() -> None:
    os.environ.setdefault("SHARIPOVAI_DISABLE_AUTH", "1")
    os.environ.setdefault("MARKET_STREAM_ENABLED", "0")
    os.environ.setdefault("FEATURE_BYBIT_WEBSOCKET", "0")
    os.environ.setdefault("BYBIT_ACCOUNT_SYNC_ENABLED", "0")
    os.environ.setdefault("EXECUTION_KILL_SWITCH", "1")
    os.environ.setdefault("EXCHANGE_LIVE_TRADING_ENABLED", "0")
    os.environ.setdefault("TESTNET_EXECUTION_ENABLED", "0")
    os.environ.setdefault("AUTONOMOUS_TESTNET_ENABLED", "0")
    os.environ.setdefault("AUTONOMOUS_TESTNET_BRIDGE_ENABLED", "0")
    os.environ.setdefault("EXCHANGE_MODE", "sandbox")
    try:
        import dashboard

        routes = list(dashboard.app.routes)
        add(2, "backend", "application_import", True, f"routes={len(routes)}", "critical")
    except Exception as exc:
        add(2, "backend", "application_import", False, f"{type(exc).__name__}: {exc}", "critical", "Исправить импорт приложения.")
        return

    owners: dict[tuple[str, str], int] = {}
    paths: set[str] = set()
    for route in routes:
        path = str(getattr(route, "path", ""))
        paths.add(path)
        for method in set(getattr(route, "methods", set()) or set()):
            key = (method, path)
            owners[key] = owners.get(key, 0) + 1
    duplicates = [f"{method} {path} x{count}" for (method, path), count in owners.items() if count > 1]
    add(2, "backend", "unique_route_ownership", not duplicates, f"duplicates={duplicates}", "high", "Убрать дубли method+path.")

    required = {
        "/health", "/api/health", "/api/run", "/api/ai-bots", "/api/social-news",
        "/api/system/database/status", "/api/system/health", "/api/system/recovery-plan",
        "/api/system/local-audit", "/api/market/bybit-websocket/status",
        "/api/exchange/account/snapshot", "/api/learning-os/status",
        "/api/evidence-vault/recent", "/api/virtual-account/state",
    }
    missing = sorted(required - paths)
    add(2, "backend", "required_api_contract", not missing, f"missing={missing}", "critical", "Восстановить обязательные API маршруты.")

    try:
        from ai_architecture_registry import CANONICAL_AI_ORGANS

        ids = [organ.id for organ in CANONICAL_AI_ORGANS]
        add(2, "ai", "canonical_ai_organs", len(ids) == 9 and len(ids) == len(set(ids)), f"organs={ids}", "critical", "Исправить канонический реестр ИИ.")
    except Exception as exc:
        add(2, "ai", "canonical_ai_organs", False, f"{type(exc).__name__}: {exc}", "critical", "Восстановить реестр ИИ.")


def static_phase_3() -> None:
    from scripts.release_audit import audit_repository

    report = audit_repository(ROOT, runtime=False)
    add(3, "infrastructure", "release_audit", report.status == "ok", f"errors={list(report.errors)}; warnings={list(report.warnings)}", "critical", "Исправить fail-closed release audit.")

    shell_errors = []
    bash = shutil.which("bash")
    if bash:
        for relative in ("deploy/vps/update_from_main.sh", "deploy/vps/remote_agent.sh"):
            path = ROOT / relative
            if path.exists():
                code, output = command([bash, "-n", str(path)])
                if code:
                    shell_errors.append(f"{relative}: {output}")
    add(3, "infrastructure", "shell_syntax", not shell_errors, f"errors={shell_errors}", "critical", "Исправить shell-синтаксис.")


def static_phase_4() -> None:
    index = ROOT / "dashboard/static/web2/index.html"
    html = index.read_text(encoding="utf-8") if index.exists() else ""
    add(4, "frontend", "web2_index", bool(html), str(index.relative_to(ROOT)), "critical", "Восстановить Web2 index.")
    if not html:
        return

    pages = re.findall(r'data-page="([^"]+)"', html)
    duplicates = sorted({page for page in pages if pages.count(page) > 1})
    add(4, "frontend", "navigation_unique", not duplicates and len(pages) >= 16, f"pages={len(pages)}; duplicates={duplicates}", "high", "Оставить один пункт на раздел.")

    assets = re.findall(r'(?:src|href)="/static/web2/([^"?]+)', html)
    missing = [asset for asset in assets if not (ROOT / "dashboard/static/web2" / asset).is_file()]
    add(4, "frontend", "assets_exist", not missing, f"assets={len(assets)}; missing={missing}", "critical", "Исправить ссылки на JS/CSS.")

    node = shutil.which("node")
    errors = []
    loaded_js = [ROOT / "dashboard/static/web2" / asset for asset in assets if asset.endswith(".js")]
    if node:
        for path in loaded_js:
            code, output = command([node, "--check", str(path)])
            if code:
                errors.append(f"{path.name}: {output}")
    add(4, "frontend", "javascript_syntax", bool(node) and not errors, f"node={bool(node)}; checked={len(loaded_js)}; errors={errors}", "critical", "Проверять JS через Node и исправить синтаксис.")

    synthetic = []
    for path in loaded_js:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("Math.random(", "mockData", "fakeData"):
            if token in text:
                synthetic.append(f"{path.name}:{token}")
    add(4, "truthfulness", "no_synthetic_loaded_data", not synthetic, f"matches={synthetic}", "critical", "Удалить синтетические данные из загружаемого интерфейса.")


def static_phase_5() -> None:
    patterns = {
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
        "telegram_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    }
    findings = []
    allowed = {".py", ".js", ".json", ".yml", ".yaml", ".sh", ".md", ".env", ".toml"}
    for path in tracked_files():
        if path.suffix.lower() not in allowed or path.name.endswith(".example"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}:{name}")
    add(5, "security", "no_committed_secrets", not findings, f"findings={findings}", "critical", "Отозвать секреты и удалить их из истории Git.")

    tests = [path for path in tracked_files() if path.suffix == ".py" and "tests" in path.parts]
    add(5, "quality", "test_suite_present", len(tests) >= 20, f"test_files={len(tests)}", "medium", "Добавить тесты критических модулей.")


def get_json(url: str, timeout: float = 8.0) -> tuple[bool, int, float, Any, str]:
    started = time.perf_counter()
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "SharipovAI-Audit/3"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            latency = (time.perf_counter() - started) * 1000
            return 200 <= response.status < 300, response.status, latency, json.loads(raw.decode("utf-8")), "ok"
    except urllib.error.HTTPError as exc:
        return False, exc.code, (time.perf_counter() - started) * 1000, None, f"HTTP {exc.code}"
    except Exception as exc:
        return False, 0, (time.perf_counter() - started) * 1000, None, f"{type(exc).__name__}: {exc}"


def live_phases(base_url: str) -> None:
    results: dict[str, Any] = {}
    for name, path, phase in (
        ("health", "/health", 3),
        ("api_health", "/api/health", 3),
        ("local_audit", "/api/system/local-audit", 5),
    ):
        ok, status, latency, data, detail = get_json(base_url.rstrip("/") + path)
        results[name] = data if isinstance(data, dict) else {}
        add(phase, "live_api", name, ok and isinstance(data, dict), f"status={status}; latency_ms={latency:.1f}; detail={detail}", "critical", f"Исправить {path}.")

    audit = results.get("local_audit", {})
    execution = audit.get("execution", {}) if isinstance(audit, dict) else {}
    locked = execution.get("kill_switch") is True and execution.get("live_enabled") is False and execution.get("testnet_enabled") is False
    add(2, "execution", "financial_execution_locked", locked, f"execution={execution}", "critical", "Включить kill switch и выключить live/testnet.")

    database = audit.get("database", {}) if isinstance(audit, dict) else {}
    add(2, "database", "canonical_database_live", database.get("status") == "ok", f"status={database.get('status')}; backend={database.get('backend')}", "critical", "Восстановить каноническую БД.")

    system = audit.get("system", {}) if isinstance(audit, dict) else {}
    components = system.get("components", []) if isinstance(system, dict) else []
    blocked = [item.get("component") for item in components if isinstance(item, dict) and item.get("status") == "blocked"]
    add(3, "runtime", "no_blocked_components", not blocked, f"system_status={system.get('status')}; blocked={blocked}", "critical", "Исправить заблокированные компоненты.")

    disk = shutil.disk_usage("/")
    used = disk.used / disk.total * 100 if disk.total else 100.0
    add(3, "vps", "disk_below_85_percent", used < 85, f"used_percent={used:.1f}; free_bytes={disk.free}", "high", "Освободить диск и настроить ротацию.")

    memory_total = memory_available = 0
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                memory_total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                memory_available = int(line.split()[1]) * 1024
    except OSError:
        pass
    used_memory = (1 - memory_available / memory_total) * 100 if memory_total else 100.0
    add(3, "vps", "memory_below_90_percent", used_memory < 90, f"used_percent={used_memory:.1f}; available_bytes={memory_available}", "high", "Найти утечку памяти.")

    ports = {}
    for port in (80, 443, 8000):
        sock = socket.socket()
        sock.settimeout(0.5)
        try:
            ports[port] = sock.connect_ex(("127.0.0.1", port)) == 0
        finally:
            sock.close()
    add(3, "vps", "expected_ports", all(ports.values()), f"ports={ports}", "high", "Восстановить приложение и HTTPS reverse proxy.")


def write_report(mode: str) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    phase_stats = {phase: {"passed": 0, "total": 0} for phase in range(1, 6)}
    severities = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in checks:
        phase_stats[item.phase]["total"] += 1
        if item.passed:
            phase_stats[item.phase]["passed"] += 1
        elif item.severity in severities:
            severities[item.severity] += 1
    phase_percent = {
        str(phase): round(data["passed"] / data["total"] * 100) if data["total"] else None
        for phase, data in phase_stats.items()
    }
    overall = round(sum(item.passed for item in checks) / len(checks) * 100) if checks else 0
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": mode,
        "overall_percent": overall,
        "phase_percent": phase_percent,
        "severity": severities,
        "checks": [asdict(item) for item in checks],
    }
    json_path = OUT / f"final-audit-{mode}.json"
    markdown_path = OUT / f"final-audit-{mode}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    names = {1: "Архитектура", 2: "ИИ и backend", 3: "Инфраструктура", 4: "Сайт", 5: "Качество и безопасность"}
    lines = [
        f"# SharipovAI — финальный аудит ({mode})",
        "",
        f"Дата: `{payload['generated_at']}`",
        f"Подтверждённая готовность этого прохода: **{overall}%**",
        "",
        "## Фазы",
    ]
    for phase in range(1, 6):
        score = phase_percent[str(phase)]
        lines.append(f"- Фаза {phase} — {names[phase]}: **{score}%**" if score is not None else f"- Фаза {phase} — {names[phase]}: не выполнялась")
    lines += ["", f"Критических: **{severities['critical']}**, высоких: **{severities['high']}**, средних: **{severities['medium']}**, низких: **{severities['low']}**", "", "## Проблемы"]
    failed = sorted((item for item in checks if not item.passed), key=lambda item: (SEVERITY_ORDER[item.severity], item.phase, item.name))
    if not failed:
        lines.append("- В границах проверки проблем не найдено.")
    for item in failed:
        lines += [
            f"### [{item.severity.upper()}] {item.name}",
            f"- Фаза: {item.phase} / {item.area}",
            f"- Подтверждение: `{item.evidence}`",
            f"- Исправление: {item.fix or 'Требуется разбор.'}",
            "",
        ]
    lines += ["## Все проверки", "", "| Фаза | Область | Проверка | Результат |", "|---:|---|---|---|"]
    for item in checks:
        lines.append(f"| {item.phase} | {item.area} | {item.name} | {'PASS' if item.passed else item.severity.upper()} |")
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"overall_percent": overall, "severity": severities, "checks": len(checks)}, ensure_ascii=False))
    return 1 if severities["critical"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("static", "live"), default="static")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    if args.mode == "static":
        static_phase_1()
        static_phase_2()
        static_phase_3()
        static_phase_4()
        static_phase_5()
    else:
        live_phases(args.base_url)
    return write_report(args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
