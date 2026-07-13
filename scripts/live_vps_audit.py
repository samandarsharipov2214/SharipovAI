from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
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
    area: str
    name: str
    passed: bool
    severity: str
    evidence: str
    fix: str = ""


checks: list[Check] = []


def add(phase: int, area: str, name: str, passed: bool, evidence: str, severity: str = "medium", fix: str = "") -> None:
    checks.append(Check(phase, area, name, passed, "none" if passed else severity, evidence, fix))


def cmd(args: list[str], timeout: int = 20, cwd: Path = ROOT) -> tuple[int, str]:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
        return result.returncode, (result.stdout + "\n" + result.stderr).strip()[-12000:]
    except Exception as exc:
        return 99, f"{type(exc).__name__}: {exc}"


def parse_env(path: Path | None) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path or not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def find_production_repo() -> Path | None:
    for item in (Path("/opt/sharipovai-repo"), Path("/opt/SharipovAI")):
        if (item / ".git").is_dir():
            return item
    return None


def find_env_file(repo: Path | None, requested: str) -> Path | None:
    candidates = []
    if requested:
        candidates.append(Path(requested))
    if repo:
        candidates += [repo / "deploy/vps/.env.vps", repo / ".env", repo / "deploy/vps/.env"]
    for path in candidates:
        if path.exists() and path.is_file():
            return path
    return None


def make_session(env: dict[str, str]) -> tuple[str, str]:
    username = env.get("ADMIN_USERNAME", "admin").strip().lower().replace(" ", "_")
    secret = env.get("AUTH_SECRET", "").strip()
    if not secret:
        seed = f"{env.get('ADMIN_PASSWORD', '')}:{env.get('BOT_TOKEN', '')}:sharipovai"
        if seed == "::sharipovai":
            return "", username
        secret = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    issued = str(int(time.time()))
    nonce = secrets.token_urlsafe(16)
    payload = f"{username}:{issued}:{nonce}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    token = base64.urlsafe_b64encode(payload.encode() + b"." + signature).decode()
    return token, username


def get_json(base: str, path: str, cookie: str, timeout: float = 10.0) -> tuple[bool, int, float, Any, str]:
    headers = {"Accept": "application/json", "User-Agent": "SharipovAI-Live-Audit/2.0"}
    if cookie:
        headers["Cookie"] = f"sharipovai_session={cookie}"
    started = time.perf_counter()
    try:
        request = urllib.request.Request(base.rstrip("/") + path, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            latency = (time.perf_counter() - started) * 1000
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception:
                data = None
            return 200 <= response.status < 300, response.status, latency, data, "ok"
    except urllib.error.HTTPError as exc:
        return False, exc.code, (time.perf_counter() - started) * 1000, None, f"HTTP {exc.code}"
    except Exception as exc:
        return False, 0, (time.perf_counter() - started) * 1000, None, f"{type(exc).__name__}: {exc}"


def extract_items(data: Any, *paths: str) -> list[Any]:
    for path in paths:
        value = data
        for key in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, list):
            return value
    return []


def audit_repo(repo: Path | None) -> None:
    add(1, "deployment", "production_repository_found", repo is not None, f"repo={repo or 'not_found'}", "critical", "Восстановить рабочий репозиторий в /opt.")
    if not repo:
        return
    code, branch = cmd(["git", "-C", str(repo), "branch", "--show-current"])
    add(1, "deployment", "production_on_main", code == 0 and branch.strip() == "main", f"branch={branch.strip()}", "high", "Переключить production на main.")
    code, head = cmd(["git", "-C", str(repo), "rev-parse", "HEAD"])
    add(1, "deployment", "production_commit_readable", code == 0 and len(head.strip()) >= 40, f"head={head.strip()[:40]}", "critical", "Исправить Git-состояние production.")
    code, dirty = cmd(["git", "-C", str(repo), "status", "--porcelain"])
    add(1, "deployment", "production_tree_clean", code == 0 and not dirty.strip(), f"dirty_files={len(dirty.splitlines()) if dirty.strip() else 0}", "high", "Сохранить нужные изменения и очистить production tree.")


def audit_api(base: str, cookie: str) -> dict[str, Any]:
    endpoints = {
        "health": "/health",
        "api_health": "/api/health",
        "auth_me": "/api/auth/me",
        "system_health": "/api/system/health",
        "recovery_plan": "/api/system/recovery-plan",
        "market_stream": "/api/market/bybit-websocket/status",
        "btc_quote": "/api/market/quote/BTCUSDT",
        "account": "/api/exchange/account/snapshot",
        "ai_bots": "/api/ai-bots",
        "decision": "/api/run",
        "news": "/api/social-news",
        "learning": "/api/learning-os/status",
        "evidence": "/api/evidence-vault/recent",
        "virtual": "/api/virtual-account/state",
        "reports": "/api/ai-control-center/daily-report",
    }
    results: dict[str, Any] = {}
    for name, path in endpoints.items():
        ok, status, latency, data, detail = get_json(base, path, cookie)
        results[name] = data if isinstance(data, dict) else {}
        passed = ok and isinstance(data, dict)
        add(2 if name in {"ai_bots", "decision", "learning"} else 5, "live_api", name, passed, f"status={status}; latency_ms={latency:.1f}; json={isinstance(data, dict)}; detail={detail}", "critical", f"Исправить живой маршрут {path}.")
    auth = results.get("auth_me", {})
    add(5, "security", "audit_authenticated", auth.get("authenticated") is True, f"authenticated={auth.get('authenticated')}; role={auth.get('role')}", "critical", "Восстановить безопасную локальную аутентификацию аудита.")
    return results


def audit_runtime(results: dict[str, Any]) -> None:
    market = results.get("market_stream", {})
    market_ok = market.get("verified") is True or str(market.get("status", "")).lower() in {"ok", "healthy", "connected", "running"}
    age = market.get("quote_age_seconds") or market.get("age_seconds")
    if age is not None:
        try:
            market_ok = market_ok and float(age) <= 5
        except Exception:
            market_ok = False
    add(3, "market", "realtime_market_verified", market_ok, f"status={market.get('status')}; verified={market.get('verified')}; age={age}", "critical", "Восстановить публичный Bybit WebSocket и свежесть котировок.")

    quote = results.get("btc_quote", {})
    price = quote.get("price") or quote.get("last_price") or quote.get("lastPrice")
    received = quote.get("received_at") or quote.get("timestamp") or quote.get("updated_at")
    add(3, "market", "btc_quote_present", price not in (None, "", 0, "0"), f"price_present={price not in (None, '', 0, '0')}; received_at={received}", "critical", "Восстановить реальные котировки BTCUSDT.")

    account = results.get("account", {})
    connected = account.get("connected") is True or account.get("verified") is True or isinstance(account.get("snapshot"), dict)
    add(3, "bybit", "private_account_read_only_connected", connected, f"connected={account.get('connected')}; verified={account.get('verified')}; snapshot={isinstance(account.get('snapshot'), dict)}", "high", "Проверить read-only ключи Bybit и IP-права.")

    bots_data = results.get("ai_bots", {})
    bots = extract_items(bots_data, "bots", "items", "agents")
    stale = []
    for bot in bots:
        if not isinstance(bot, dict):
            continue
        age_value = bot.get("heartbeat_age_seconds")
        try:
            if age_value is None or float(age_value) > 90:
                stale.append(str(bot.get("name") or bot.get("id") or "unknown"))
        except Exception:
            stale.append(str(bot.get("name") or bot.get("id") or "unknown"))
    add(2, "ai", "ai_registry_nonempty", bool(bots), f"bots={len(bots)}", "critical", "Восстановить реестр ИИ.")
    add(2, "ai", "ai_heartbeats_fresh", bool(bots) and not stale, f"bots={len(bots)}; stale={stale}", "high", "Восстановить heartbeat зависших ИИ.")

    decision = results.get("decision", {})
    decision_value = decision.get("decision") or decision.get("action") or decision.get("status")
    add(2, "ai", "general_ai_output_present", bool(decision_value), f"decision_present={bool(decision_value)}", "high", "Восстановить выход General AI и его доказательства.")

    news_data = results.get("news", {})
    news = extract_items(news_data, "news.items", "news", "items", "articles")
    add(3, "news", "news_feed_nonempty", bool(news), f"items={len(news)}", "high", "Восстановить источники News AI.")

    evidence = extract_items(results.get("evidence", {}), "items", "records", "events")
    add(2, "evidence", "evidence_vault_records", bool(evidence), f"records={len(evidence)}", "high", "Восстановить запись цепочки данных → решение → действие → результат.")

    system = results.get("system_health", {})
    components = extract_items(system, "components")
    blocked = [x.get("component") for x in components if isinstance(x, dict) and x.get("status") == "blocked"]
    degraded = [x.get("component") for x in components if isinstance(x, dict) and x.get("status") == "degraded"]
    add(3, "health", "no_blocked_components", not blocked, f"blocked={blocked}; degraded={degraded}", "critical", "Исправить заблокированные компоненты из /api/system/health.")


def port_open(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(0.7)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def audit_system() -> None:
    disk = shutil.disk_usage("/")
    used = disk.used / disk.total * 100 if disk.total else 100
    add(3, "vps", "disk_below_85_percent", used < 85, f"used_percent={used:.1f}; free_bytes={disk.free}", "high", "Освободить диск и настроить ротацию.")

    mem_total = mem_available = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                mem_available = int(line.split()[1]) * 1024
    except Exception:
        pass
    mem_used = (1 - mem_available / mem_total) * 100 if mem_total else 100
    add(3, "vps", "memory_below_90_percent", mem_used < 90, f"used_percent={mem_used:.1f}; available_bytes={mem_available}", "high", "Найти утечку или увеличить память.")

    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0
    cpus = os.cpu_count() or 1
    add(3, "vps", "load_below_2x_cpu", load1 < cpus * 2, f"load1={load1:.2f}; cpus={cpus}", "medium", "Найти перегружающий процесс.")

    ports = {p: port_open(p) for p in (80, 443, 8000)}
    add(3, "vps", "application_port_8000", ports[8000], f"ports={ports}", "critical", "Запустить приложение на 127.0.0.1:8000.")
    add(3, "vps", "public_http_https", ports[80] and ports[443], f"ports={ports}", "high", "Восстановить reverse proxy и HTTPS.")

    code, docker_state = cmd(["systemctl", "is-active", "docker"])
    add(3, "vps", "docker_service_active", code == 0 and docker_state.strip() == "active", f"state={docker_state.strip()}", "high", "Запустить Docker.")

    code, docker_ps = cmd(["docker", "ps", "--format", "{{.Names}}|{{.Status}}"])
    visible = code == 0
    containers = [line.strip() for line in docker_ps.splitlines() if "|" in line]
    add(3, "vps", "docker_runtime_visible", visible, f"visible={visible}; containers={len(containers)}", "high", "Дать runner безопасный read-only доступ к Docker либо запускать аудит через root agent.")
    names = {line.split("|", 1)[0] for line in containers}
    add(3, "vps", "application_container_running", "sharipovai" in names, f"containers={sorted(names)}", "critical", "Восстановить контейнер sharipovai.")
    add(3, "vps", "caddy_container_running", "sharipovai-caddy" in names, f"containers={sorted(names)}", "high", "Восстановить контейнер Caddy.")

    code, runner = cmd(["bash", "-lc", "systemctl list-units --type=service --state=running --no-legend | awk '$1 ~ /^actions\\.runner\\./ {print $1; exit}'"])
    add(3, "vps", "actions_runner_active", code == 0 and bool(runner.strip()), f"runner_active={bool(runner.strip())}", "medium", "Восстановить self-hosted runner.")


def write_report(env_file: Path | None, username: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    phase_stats: dict[int, dict[str, int]] = {i: {"passed": 0, "total": 0} for i in range(1, 6)}
    severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for item in checks:
        phase_stats[item.phase]["total"] += 1
        if item.passed:
            phase_stats[item.phase]["passed"] += 1
        elif item.severity in severity:
            severity[item.severity] += 1
    phase_scores = {str(k): round(v["passed"] / v["total"] * 100) if v["total"] else None for k, v in phase_stats.items()}
    overall = round(sum(x.passed for x in checks) / len(checks) * 100) if checks else 0
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": "live",
        "overall_percent": overall,
        "phase_percent": phase_scores,
        "severity": severity,
        "audit_identity": username,
        "env_file_found": bool(env_file),
        "checks": [asdict(x) for x in checks],
    }
    (OUT / "audit-live.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    names = {1: "Архитектура развёртывания", 2: "ИИ и backend", 3: "Инфраструктура и данные", 4: "Сайт", 5: "Живая система и безопасность"}
    lines = ["# SharipovAI — живой аудит VPS", "", f"Дата: `{payload['generated_at']}`", f"Подтверждённая готовность живой системы: **{overall}%**", f"Локальная авторизация: **{'подтверждена' if any(x.name == 'audit_authenticated' and x.passed for x in checks) else 'не подтверждена'}**", "", "## Фазы"]
    for i in range(1, 6):
        score = phase_scores[str(i)]
        lines.append(f"- Фаза {i} — {names[i]}: **{score}%**" if score is not None else f"- Фаза {i} — {names[i]}: не выполнялась в live-проходе")
    lines += ["", f"Критических: **{severity['critical']}**, высоких: **{severity['high']}**, средних: **{severity['medium']}**, низких: **{severity['low']}**", "", "## Проблемы"]
    failed = [x for x in checks if not x.passed]
    if not failed:
        lines.append("- В границах проверки проблем не найдено.")
    for item in sorted(failed, key=lambda x: ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x.severity, 4), x.phase)):
        lines += [f"### [{item.severity.upper()}] {item.name}", f"- Фаза: {item.phase} / {item.area}", f"- Подтверждение: `{item.evidence}`", f"- Исправление: {item.fix}", ""]
    lines += ["## Все проверки", "", "| Фаза | Область | Проверка | Результат |", "|---:|---|---|---|"]
    for item in checks:
        lines.append(f"| {item.phase} | {item.area} | {item.name} | {'PASS' if item.passed else item.severity.upper()} |")
    (OUT / "audit-live.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"overall_percent": overall, "severity": severity, "checks": len(checks)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--env-file", default="")
    args = parser.parse_args()

    repo = find_production_repo()
    env_file = find_env_file(repo, args.env_file)
    env = parse_env(env_file)
    cookie, username = make_session(env)
    add(5, "security", "production_env_available", bool(env_file), f"env_file_found={bool(env_file)}", "critical", "Указать путь к deploy/vps/.env.vps для локального аудита.")
    add(5, "security", "session_cookie_created", bool(cookie), f"cookie_created={bool(cookie)}; username={username}", "critical", "Настроить AUTH_SECRET или административные параметры.")

    audit_repo(repo)
    results = audit_api(args.base_url, cookie)
    audit_runtime(results)
    audit_system()
    write_report(env_file, username)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
