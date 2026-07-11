# SharipovAI Windows PC Node

SharipovAI can run on a Windows PC through one self-healing supervisor: **PC Agent**.

PC Agent watches and restarts:

- Dashboard/FastAPI on `http://127.0.0.1:8000`;
- the persistent backup loop;
- health and backup freshness status.

It also provides:

- an isolated `.venv` Python environment;
- a single-instance lock;
- observable PID and status files;
- startup/error logs under `runtime/logs`;
- automatic verification after setup and updates;
- safe ZIP updates with rollback.

## One-command installation

Run from the project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap_pc_node.ps1
```

The bootstrap performs setup, installs Windows autostart for the current user, launches PC Agent, and verifies:

- writable persistent data;
- a fresh verified backup manifest;
- the Dashboard `/health` endpoint;
- a live and fresh PC Agent status.

The installation report is stored at:

```text
runtime/pc_node_installation.json
```

## Runtime files

```text
runtime/pids/pc_agent.pid
runtime/pc_agent_status.json
runtime/logs/pc_agent.stdout.log
runtime/logs/pc_agent.stderr.log
runtime/logs/pc_agent.jsonl
runtime/logs/pc_node.log
runtime/logs/pc_backup.log
```

Repeated start commands are safe. A healthy agent is reused instead of starting a duplicate.

## Manual start and verification

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start_pc_agent.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\check_pc_node.ps1 -RequireManagedProcesses
```

The older `start_pc_node.ps1` and `start_backup.ps1` remain available only as emergency/manual launchers. Normal operation and autostart should use PC Agent.

## Safe updater

The Windows updater installs a ZIP archive without touching local secrets or runtime state.

Protected top-level paths:

- `.env`
- `.env.local`
- `.git`
- `.venv`
- `data`
- `runtime`

Before changing code it creates a rollback snapshot under:

```text
runtime/update_backups/<UTC timestamp>
```

After copying the update it validates all Python files. If validation fails, the previous code is restored automatically. A successful update restarts the unified PC Agent and runs the managed health check.

Usage:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\update_pc_node.ps1 -Archive "C:\path\to\SharipovAI-main.zip"
```

The last update report is stored at:

```text
runtime/last_update.json
```

Previous code snapshots remain in `runtime/update_backups` for recovery.
