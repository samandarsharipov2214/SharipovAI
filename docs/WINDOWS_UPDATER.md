# SharipovAI Windows updater

The Windows updater installs a ZIP archive of the repository without touching local secrets or runtime state.

## Protected local paths

The updater never replaces these top-level paths:

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

## Usage

1. Download the latest repository ZIP in the browser.
2. Run from the project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\update_pc_node.ps1 -Archive "C:\path\to\SharipovAI-main.zip"
```

The wrapper stops the local server and backup process, applies the update, fixes PowerShell 5.1 encoding, starts both processes again, and runs the PC-node health check.

## Recovery

The last successful update report is stored at:

```text
runtime/last_update.json
```

Previous code snapshots remain in `runtime/update_backups` and can be restored manually if needed.
