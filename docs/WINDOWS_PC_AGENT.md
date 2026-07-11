# SharipovAI Windows PC Agent

`tools/pc_node_agent.py` is the single supervisor for a local Windows node.

It performs these checks every 15 seconds by default:

- `http://127.0.0.1:8000/health`;
- freshness of `runtime/backups/current/manifest.json`;
- restart cooldown to avoid process storms;
- single-instance lock in `runtime/pc_agent.lock`.

When the web node or backup loop is unavailable, the agent starts it again in a hidden process. It writes:

- current status to `runtime/pc_agent_status.json`;
- structured events to `runtime/logs/pc_agent.jsonl`;
- node output to `runtime/logs/pc_node.log`;
- backup output to `runtime/logs/pc_backup.log`.

The agent does not enable live trading and does not modify `.env.local` or secrets.

## Windows autostart

Run once:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\install_autostart.ps1
```

The installer removes the two legacy shortcuts and creates one `SharipovAI PC Agent` shortcut.

## Manual one-shot check

```powershell
.\.venv\Scripts\python.exe .\tools\pc_node_agent.py --project-root . --once
```

Optional `.env.local` settings:

```text
PC_AGENT_INTERVAL_SECONDS=15
PC_AGENT_BACKUP_MAX_AGE_SECONDS=45
PC_AGENT_RESTART_COOLDOWN_SECONDS=30
```
