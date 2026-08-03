# SharipovAI Self-Healing Agent

## Architecture

The Python agent runs inside the `sharipovai` container. A small host-side shell
wrapper is required because an in-container process cannot restart a stopped
container or safely replace the database file while its own application is
running.

The host wrapper does not need Python. It performs only allow-listed actions:

- `docker compose up -d`;
- restart `sharipovai` or `caddy`;
- atomically install a database candidate already verified by the Python agent;
- revert the exact current commit only when its subject starts with
  `[self-healing]` and the tracked worktree is clean.

The Docker socket is deliberately **not** mounted into the application
container. Mounting it would grant the web application root-equivalent control
of the VPS.

## Checks performed every 15 minutes

- `sharipovai` and `sharipovai-caddy` existence/running state;
- `http://127.0.0.1:8000/health`;
- SQLite `PRAGMA integrity_check` for
  `/var/lib/sharipovai/sharipovai_shared.db`;
- verified restore candidate from
  `deploy/vps/backups/latest.tar.gz`;
- fresh `ERROR`, `CRITICAL`, `FATAL` and Python traceback entries from the last
  15 minutes of Docker logs;
- related pytest files for changed repository paths;
- safe revert request for a failing automatic commit;
- Bybit public WebSocket status at
  `/api/market/bybit-websocket/status`, with a Telegram alert after five minutes
  of disconnection.

Agent log:

```text
/var/lib/sharipovai/agent.log
```

Host wrapper log:

```text
/var/log/sharipovai-self-healing-host.log
```

## Installation

From the repository root on the VPS:

```bash
cd /opt/sharipovai-repo
git pull --ff-only origin main
bash deploy/vps/install_self_healing_agent.sh
```

The installer recreates the application container to activate the read-only
`/workspace` bind mount, installs the systemd service and timer, enables the
timer, and runs the first cycle.

## Manual run

```bash
systemctl start sharipovai-self-healing.service
systemctl --no-pager --full status sharipovai-self-healing.service
journalctl -u sharipovai-self-healing.service -n 100 --no-pager
```

Run the Python agent directly inside the container without requesting repairs:

```bash
docker exec --user 0 \
  -e SELF_HEALING_REPO_DIR=/workspace \
  sharipovai \
  python /workspace/tools/self_healing_agent.py --verify-only
```

Inspect the timer:

```bash
systemctl list-timers sharipovai-self-healing.timer --all
```

Inspect the persistent agent state:

```bash
docker exec --user 0 sharipovai sh -lc \
  'tail -n 100 /var/lib/sharipovai/agent.log; echo; cat /var/lib/sharipovai/.self_healing/state.json'
```

## Telegram

The agent reads `BOT_TOKEN` and `TELEGRAM_OWNER_ID` from the existing container
environment. Alerts are deduplicated with a one-hour default cooldown.

## Safe rollback rule

The agent never resets an arbitrary operator commit. Automatic rollback is
allowed only when all conditions are true:

1. the failing commit is the exact current `HEAD`;
2. its subject starts with `[self-healing]`;
3. the tracked worktree is clean;
4. related tests failed in an isolated temporary repository snapshot.

The wrapper uses `git revert`, preserving the audit trail.
