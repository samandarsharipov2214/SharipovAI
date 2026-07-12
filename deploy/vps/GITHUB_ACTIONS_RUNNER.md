# SharipovAI self-hosted CI

GitHub-hosted Actions are not used by the project workflows. Linux checks run on the main VPS with label `sharipovai-ci`; Windows packaging runs on the standby PC with label `sharipovai-windows-ci`.

## Safety model

- The VPS runner uses the dedicated unprivileged account `sharipov-ci`.
- The runner account is not added to the Docker group and cannot access the Docker socket.
- Pull requests from forks are not executed on self-hosted runners.
- Trading flags, exchange credentials and production `.env.vps` are not passed to CI jobs.
- Workflows remain skipped until the corresponding repository variable is set to `1`.

## VPS runner

The repository is already located at `/opt/sharipovai-repo` on the VPS.

Use a short-lived runner registration token in `GITHUB_RUNNER_TOKEN`, or an administrator token in `GH_TOKEN`. When `GH_TOKEN` is used, the installer also sets `SHARIPOVAI_SELF_HOSTED_CI=1` automatically.

```bash
cd /opt/sharipovai-repo
git fetch origin
git checkout main
git pull --ff-only origin main
read -rsp 'GitHub token: ' GH_TOKEN && echo
export GH_TOKEN
sudo -E bash deploy/vps/install_github_actions_runner.sh
unset GH_TOKEN
```

Remove the runner safely:

```bash
cd /opt/sharipovai-repo
read -rsp 'GitHub token: ' GH_TOKEN && echo
export GH_TOKEN
sudo -E bash deploy/vps/uninstall_github_actions_runner.sh
unset GH_TOKEN
```

## Windows standby runner

Run PowerShell as Administrator on the standby PC:

```powershell
$env:GH_TOKEN = Read-Host 'GitHub token' -MaskInput
Set-Location C:\SharipovAI
.\scripts\windows\install_github_actions_runner.ps1
Remove-Item Env:\GH_TOKEN
```

The installer registers the service and sets `SHARIPOVAI_WINDOWS_SELF_HOSTED_CI=1` when the token permits repository-variable updates.

## Workflow allocation

- `Tests`: Python regression tests on VPS.
- `Project Guardrails`: database migration, fail-closed audit and execution safety on VPS.
- `Dashboard Stabilization`: targeted dashboard tests on VPS.
- `Full Stabilization Suite`: weekly or manual full suite on VPS.
- `Windows Agent Package`: PowerShell validation, PC-node tests and ZIP package on the standby PC.
