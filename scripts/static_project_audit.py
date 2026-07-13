from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "audit-results"


@dataclass
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


def command(args: list[str], timeout: int = 120, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env, check=False)
        return result.returncode, (result.stdout + "\n" + result.stderr).strip()[-20000:]
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def files() -> list[Path]:
    code, text = command(["git", "ls-files"])
    if code:
        return []
    return [ROOT / line for line in text.splitlines() if line.strip() and (ROOT / line).is_file()]


def architecture() -> None:
    tracked = files()
    py = [p for p in tracked if p.suffix == ".py"]
    errors: list[str] = []
    for path in py:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception as exc:
            errors.append(f"{path.relative_to(ROOT)}: {exc}")
    add(1, "architecture", "python_syntax", not errors, f"python_files={len(py)}; errors={errors[:20]}", "critical", "Исправить синтаксис Python.")

    init = ROOT / "dashboard/__init__.py"
    text = init.read_text(encoding="utf-8") if init.exists() else ""
    calls = re.findall(r"^\s*(install_[A-Za-z0-9_]+)\(app\)", text, re.M)
    duplicate_calls = sorted({name for name in calls if calls.count(name) > 1})
    add(1, "architecture", "canonical_entrypoint", bool(text and calls), f"installer_calls={len(calls)}", "critical", "Восстановить единую точку сборки dashboard.app.")
    add(1, "architecture", "installer_calls_unique", not duplicate_calls, f"duplicates={duplicate_calls}", "high", "Удалить повторную установку API-модулей.")

    old = [p for p in (ROOT / "dashboard/templates/index.html", ROOT / "dashboard/static/mini-app-live.js") if p.exists()]
    add(1, "architecture", "old_site_removed", not old, f"remaining={[str(p.relative_to(ROOT)) for p in old]}", "medium", "Удалить остатки старого интерфейса.")

    requirements = ROOT / "requirements.txt"
    lines = [x.strip() for x in requirements.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")] if requirements.exists() else []
    broad = [x for x in lines if ">=" in x or "~=" in x or "*" in x]
    lock_exists = any((ROOT / name).exists() for name in ("poetry.lock", "uv.lock", "requirements.lock", "requirements.txt.lock"))
    add(1, "dependencies", "dependency_lock", lock_exists or not broad, f"dependencies={len(lines)}; broad={broad}; lock={lock_exists}", "medium", "Зафиксировать проверенные версии зависимостей.")

    oversized = []
    for path in tracked:
        try:
            if path.stat().st_size > 1_000_000:
                oversized.append(f"{path.relative_to(ROOT)}={path.stat().st_size}")
        except OSError:
            pass
    add(1, "architecture", "no_oversized_tracked_files", not oversized, f"oversized={oversized[:30]}", "low", "Убрать генерируемые/бинарные данные из Git.")


def backend_and_ai() -> None:
    env = os.environ.copy()
    env.update({
        "ENVIRONMENT": "test",
        "SHARIPOVAI_DISABLE_AUTH": "1",
        "EXECUTION_KILL_SWITCH": "1",
        "EXCHANGE_LIVE_TRADING_ENABLED": "0",
        "TESTNET_EXECUTION_ENABLED": "0",
        "FEATURE_BYBIT_WEBSOCKET": "0",
        "MARKET_STREAM_ENABLED": "0",
        "SHARIPOVAI_DATA_DIR": "/tmp/sharipovai-static-audit",
    })
    probe = r'''
import json
import dashboard
rows=[]
for route in dashboard.app.routes:
    rows.append({"path": getattr(route,"path",""), "methods": sorted(getattr(route,"methods",[]) or [])})
print("AUDIT_ROUTES="+json.dumps(rows, ensure_ascii=False))
'''
    code, output = command([sys.executable, "-c", probe], timeout=45, env=env)
    marker = next((line for line in output.splitlines() if line.startswith("AUDIT_ROUTES=")), "")
    routes = []
    if marker:
        try:
            routes = json.loads(marker.split("=", 1)[1])
        except json.JSONDecodeError:
            pass
    add(2, "backend", "application_import", code == 0 and bool(routes), f"returncode={code}; route_count={len(routes)}; tail={output[-1000:]}", "critical", "Исправить импорт и инициализацию FastAPI.")
    if not routes:
        return

    ownership: dict[tuple[str, str], int] = {}
    paths = set()
    for route in routes:
        path = str(route.get("path", ""))
        paths.add(path)
        for method in route.get("methods", []):
            key = (method, path)
            ownership[key] = ownership.get(key, 0) + 1
    duplicates = [f"{method} {path} x{count}" for (method, path), count in ownership.items() if count > 1]
    add(2, "backend", "route_ownership_unique", not duplicates, f"routes={len(routes)}; duplicates={duplicates}", "critical", "Оставить одного владельца каждого method+path.")

    required = {
        "/health", "/api/health", "/api/run", "/api/ai-bots", "/api/social-news",
        "/api/exchange/account/snapshot", "/api/market/bybit-websocket/status",
        "/api/learning-os/status", "/api/evidence-vault/recent", "/api/virtual-account/state",
        "/api/ai-control-center/daily-report", "/api/system/health", "/api/system/recovery-plan",
    }
    missing = sorted(required - paths)
    add(2, "backend", "required_contracts", not missing, f"missing={missing}", "critical", "Восстановить обязательные маршруты нового сайта.")

    init_text = (ROOT / "dashboard/__init__.py").read_text(encoding="utf-8")
    organs = {
        "database": "install_database_api", "news": "install_news_agent_network_api",
        "market": "install_market_data_api", "execution": "install_execution_stages_api",
        "bybit": "install_bybit_account_api", "control": "install_control_plane_api",
        "monitor": "install_ai_organ_state_api", "health": "install_system_health_api",
        "watchdog": "install_system_watchdog",
    }
    missing_organs = [name for name, token in organs.items() if token not in init_text]
    add(2, "ai", "core_organs_registered", not missing_organs, f"missing={missing_organs}", "critical", "Подключить отсутствующий существующий орган без создания дубля.")

    compose = (ROOT / "deploy/vps/docker-compose.yml").read_text(encoding="utf-8") if (ROOT / "deploy/vps/docker-compose.yml").exists() else ""
    safe = "EXCHANGE_LIVE_TRADING_ENABLED: \"0\"" in compose and "EXECUTION_KILL_SWITCH: \"1\"" in compose
    add(2, "security", "production_trading_locked", safe, "compose_has_live_off_and_kill_switch_on=" + str(safe), "critical", "Зафиксировать live=0 и kill-switch=1 в VPS-конфигурации.")


def infrastructure() -> None:
    required = ["Dockerfile", "deploy/vps/docker-compose.yml", "deploy/vps/Caddyfile", "deploy/vps/update_from_main.sh", "deploy/vps/remote_agent.sh", ".github/workflows/vps-recovery.yml"]
    missing = [x for x in required if not (ROOT / x).exists()]
    add(3, "infrastructure", "deployment_contract", not missing, f"missing={missing}", "high", "Восстановить единый VPS-контур.")

    bash = shutil.which("bash")
    errors = []
    if bash:
        for rel in ("deploy/vps/update_from_main.sh", "deploy/vps/remote_agent.sh"):
            path = ROOT / rel
            if path.exists():
                code, output = command([bash, "-n", str(path)])
                if code:
                    errors.append(f"{rel}: {output}")
    add(3, "infrastructure", "shell_syntax", not errors, f"errors={errors}", "critical", "Исправить shell-синтаксис.")

    compose_text = (ROOT / "deploy/vps/docker-compose.yml").read_text(encoding="utf-8") if (ROOT / "deploy/vps/docker-compose.yml").exists() else ""
    expected = ["restart: unless-stopped", "127.0.0.1:8000:8000", "healthcheck:", "caddy:", ".env.vps"]
    absent = [x for x in expected if x not in compose_text]
    add(3, "infrastructure", "compose_safety_contract", not absent, f"missing_markers={absent}", "high", "Исправить restart, healthcheck, loopback-port и reverse proxy.")

    workflow_text = (ROOT / ".github/workflows/vps-recovery.yml").read_text(encoding="utf-8") if (ROOT / ".github/workflows/vps-recovery.yml").exists() else ""
    forbidden = [x for x in ("EXCHANGE_LIVE_TRADING_ENABLED=1", "TESTNET_EXECUTION_ENABLED=1", "EXECUTION_KILL_SWITCH=0") if x in workflow_text]
    add(3, "security", "ci_never_enables_trading", not forbidden, f"forbidden={forbidden}", "critical", "Запретить CI включать торговлю.")


def frontend() -> None:
    index = ROOT / "dashboard/static/web2/index.html"
    html = index.read_text(encoding="utf-8") if index.exists() else ""
    add(4, "frontend", "web2_index", bool(html), str(index.relative_to(ROOT)), "critical", "Восстановить новый интерфейс Web2.")
    if not html:
        return

    pages = re.findall(r'data-page="([^"]+)"', html)
    duplicated_pages = sorted({p for p in pages if pages.count(p) > 1})
    add(4, "frontend", "navigation_unique", not duplicated_pages, f"pages={len(pages)}; duplicates={duplicated_pages}", "high", "Убрать повторные пункты меню.")

    assets = re.findall(r'(?:src|href)="(/static/web2/[^"]+)"', html)
    missing = []
    js = []
    for item in assets:
        clean = item.split("?", 1)[0].removeprefix("/static/web2/")
        path = ROOT / "dashboard/static/web2" / clean
        if not path.exists():
            missing.append(item)
        elif path.suffix == ".js":
            js.append(path)
    add(4, "frontend", "assets_exist", not missing, f"assets={len(assets)}; missing={missing}", "critical", "Исправить отсутствующие JS/CSS-файлы.")

    node = shutil.which("node")
    js_errors = []
    if node:
        for path in js:
            code, output = command([node, "--check", str(path)])
            if code:
                js_errors.append(f"{path.name}: {output}")
    add(4, "frontend", "javascript_syntax", bool(node) and not js_errors, f"node={bool(node)}; checked={len(js)}; errors={js_errors}", "critical", "Установить Node в CI и исправить JS-синтаксис.")

    synthetic = []
    for path in js:
        body = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("Math.random(", "mockData", "fakeData", "demoData"):
            if token in body:
                synthetic.append(f"{path.name}:{token}")
    add(4, "truthfulness", "no_synthetic_runtime_data", not synthetic, f"matches={synthetic}", "critical", "Удалить демонстрационные данные из рабочего интерфейса.")

    coordinator = ROOT / "dashboard/static/web2/navigation_coordinator_v23.js"
    body = coordinator.read_text(encoding="utf-8") if coordinator.exists() else ""
    stack_guard = "Object.defineProperty(content, 'innerHTML'" in body and "new Error().stack" in body
    add(4, "frontend", "explicit_render_router", not stack_guard, f"stack_based_innerHTML_guard={stack_guard}", "high", "Заменить перехват innerHTML через stack trace на единый router/render API.")


def security_quality() -> None:
    patterns = {
        "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
        "telegram_token": re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b"),
    }
    findings = []
    for path in files():
        if path.suffix.lower() not in {".py", ".js", ".json", ".yml", ".yaml", ".sh", ".md", ".env", ".toml"}:
            continue
        if path.name.endswith(".example"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in patterns.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(ROOT)}:{name}")
    add(5, "security", "no_committed_secrets", not findings, f"findings={findings}", "critical", "Отозвать секреты и удалить их из истории Git.")

    tests = [p for p in files() if p.parts and "tests" in p.parts and p.suffix == ".py"]
    add(5, "quality", "test_suite_present", len(tests) >= 20, f"test_files={len(tests)}", "medium", "Добавить тесты критических API, сайта и VPS.")


def report() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    phases: dict[int, dict[str, int]] = {i: {"passed": 0, "total": 0} for i in range(1, 6)}
    severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in checks:
        phases[item.phase]["total"] += 1
        if item.passed:
            phases[item.phase]["passed"] += 1
        elif item.severity in severity:
            severity[item.severity] += 1
    scores = {str(k): round(v["passed"] / v["total"] * 100) if v["total"] else None for k, v in phases.items()}
    overall = round(sum(x.passed for x in checks) / len(checks) * 100) if checks else 0
    payload = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "type": "static", "overall_percent": overall, "phase_percent": scores, "severity": severity, "checks": [asdict(x) for x in checks]}
    (OUT / "audit-static.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    names = {1: "Архитектура", 2: "ИИ и backend", 3: "Инфраструктура", 4: "Сайт", 5: "Безопасность и качество"}
    lines = ["# SharipovAI — статический аудит", "", f"Дата: `{payload['generated_at']}`", f"Подтверждённая готовность: **{overall}%**", "", "## Фазы"]
    for i in range(1, 6):
        lines.append(f"- Фаза {i} — {names[i]}: **{scores[str(i)]}%**")
    lines += ["", f"Критических: **{severity['critical']}**, высоких: **{severity['high']}**, средних: **{severity['medium']}**, низких: **{severity['low']}**", "", "## Проблемы"]
    failed = [x for x in checks if not x.passed]
    for item in sorted(failed, key=lambda x: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.severity, 4), x.phase)):
        lines += [f"### [{item.severity.upper()}] {item.name}", f"- Фаза: {item.phase} / {item.area}", f"- Подтверждение: `{item.evidence}`", f"- Исправление: {item.fix}", ""]
    lines += ["## Все проверки", "", "| Фаза | Область | Проверка | Результат |", "|---:|---|---|---|"]
    for item in checks:
        lines.append(f"| {item.phase} | {item.area} | {item.name} | {'PASS' if item.passed else item.severity.upper()} |")
    (OUT / "audit-static.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"overall_percent": overall, "severity": severity, "checks": len(checks)}, ensure_ascii=False))


def main() -> int:
    architecture()
    backend_and_ai()
    infrastructure()
    frontend()
    security_quality()
    report()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
