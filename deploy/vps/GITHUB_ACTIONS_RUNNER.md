# SharipovAI self-hosted CI

GitHub-hosted Actions are not used by project workflows. Linux checks run on the main VPS with label `sharipovai-ci`; Windows packaging runs on the standby PC with label `sharipovai-windows-ci`.

## Safety model

- The VPS runner uses the dedicated unprivileged account `sharipov-ci`.
- The runner account is not added to the Docker group and cannot access the Docker socket.
- Pull requests from forks are not executed on self-hosted runners.
- Trading flags, exchange credentials and production `.env.vps` are not passed to CI jobs.
- Workflows remain skipped until the corresponding repository variable is set to `1`.

## One-command VPS bootstrap

The bootstrap finds `/opt/sharipovai-repo` or `/opt/SharipovAI`, updates `main`, performs GitHub device authorization once, installs the runner service, enables `SHARIPOVAI_SELF_HOSTED_CI=1`, starts a real workflow and waits for a passing result.

```bash
cd /opt/sharipovai-repo
git fetch origin main
git checkout main
git pull --ff-only origin main
bash deploy/vps/bootstrap_github_actions_runner.sh
```

During the first run GitHub CLI prints a one-time device code. Approve that code in the browser. The temporary CLI authorization is removed automatically after installation when the server did not already have a GitHub CLI session.

## Non-interactive VPS installer

For automation, use a short-lived runner registration token in `GITHUB_RUNNER_TOKEN`, or an administrator token in `GH_TOKEN`. When `GH_TOKEN` is used, the installer also sets `SHARIPOVAI_SELF_HOSTED_CI=1` automatically.

```bash
cd /opt/sharipovai-repo
read -rsp 'GitHub token: ' GH_TOKEN && echo
export GH_TOKEN
bash deploy/vps/install_github_actions_runner.sh
unset GH_TOKEN
```

Remove safely:

```bash
cd /opt/sharipovai-repo
read -rsp 'GitHub token: ' GH_TOKEN && echo
export GH_TOKEN
bash deploy/vps/uninstall_github_actions_runner.sh
unset GH_TOKEN
```

## Windows standby runner

Run PowerShell as Administrator:

```powershell
$env:GH_TOKEN = Read-Host 'GitHub token' -MaskInput
Set-Location C:\SharipovAI
.\scripts\windows\install_github_actions_runner.ps1
Remove-Item Env:\GH_TOKEN
```

The installer registers the service and sets `SHARIPOVAI_WINDOWS_SELF_HOSTED_CI=1` when the token permits repository-variable updates.

## Workflow allocation

- `Проверка SharipovAI`: full Python verification on VPS.
- `Tests`: Python regression tests on VPS.
- `Project Guardrails`: database migration, fail-closed audit and execution safety on VPS.
- `Dashboard Stabilization`: targeted dashboard tests on VPS.
- `Full Stabilization Suite`: weekly or manual full suite on VPS.
- `Production Smoke`: hourly deployed-service check on VPS.
- `SharipoAI Web 2`: frontend lint/build/runtime smoke on VPS.
- `Sync official Bybit trading skill`: manual verified upstream sync on VPS.
- `Windows Agent Package`: PowerShell validation, PC-node tests and ZIP package on the standby PC.
