# SharipovAI Windows PC Node

SharipovAI can run on a Windows PC as a managed local node with:

- Dashboard/FastAPI on `http://127.0.0.1:8000`;
- an isolated `.venv` Python environment;
- a persistent backup loop;
- PID files that prevent duplicate processes;
- startup and error logs under `runtime/logs`;
- automatic health verification;
- safe ZIP updates with rollback.

## One-command installation

Run from the project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\bootstrap_pc_node.ps1
```

The bootstrap performs setup, installs Windows autostart for the current user, starts the backup loop and web node, then verifies:

- writable persistent data;
- a fresh verified backup manifest;
- the `/health` endpoint;
- managed PC Node and Backup PIDs.

The final installation report is stored at:

```text
runtime/pc_node_installation.json
```

## Runtime files

```text
runtime/pids/pc_node.pid
runtime/pids/backup.pid
runtime/logs/pc_node.stdout.log
runtime/logs/pc_node.stderr.log
runtime/logs/backup.stdout.log
runtime/logs/backup.stderr.log
runtime/pc_node_status.json
runtime/backup_status.json
```

Repeated startup commands are safe: an already healthy process is reused instead of starting a duplicate.

## Manual start and verification

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start_backup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start_pc_node.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\check_pc_node.ps1 -RequireManagedProcesses
```

## Safe updater

The Windows updater installs a ZIP archive of the repository without touching local secrets or runtime state.

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

After copying the update it validates all Python files. If validation fails, the previous code is restored automatically.

Usage:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\update_pc_node.ps1 -Archive "C:\path\to\SharipovAI-main.zip"
```

The last update report is stored at:

```text
runtime/last_update.json
```

Previous code snapshots remain in `runtime/update_backups` for recovery.
