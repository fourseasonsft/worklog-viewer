# FSFT Worklog Viewer

Read-only Flask viewer for the FSFT worklog markdown repository.

## Purpose

- KB = how the platform works
- Worklog = what we did, what is next, bugs, features, support issues, and where we left off
- Codex should update the Worklog after meaningful work
- Codex should update the KB only when architecture, runbooks, infrastructure, auth, deployment, or business rules change
- Use the KB for workflow and platform guidance:
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/index.md`
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-overview.md`
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-daily-workflow.md`
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-viewer.md`
- The viewer is read-only but contains internal project information and should be protected with Cloudflare Access before broad external exposure
- Long-term external access should eventually move to Core/Unity SSO, not a local Worklog login

## Content Root

The viewer reads markdown from:

- `/opt/fsftdev/fsft-worklog`

## Viewer URL

- Local development: `http://127.0.0.1:5075`
- DEV hostname: `https://worklog.fsftdev.com` when the host-level reverse proxy and tunnel are configured

## Start

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

For the standard FSFT DEV service flow, use the example systemd unit under `deployment/`.

The app listens on:

- `http://127.0.0.1:5075`

## Restart

```bash
pkill -f 'worklog-viewer/app.py' || true
python3 app.py
```

If the app is deployed with systemd, restart the service instead:

```bash
sudo systemctl restart worklog-dev.service
sudo systemctl status worklog-dev.service --no-pager
```

## Routes

- `/`
- `/roadmap`
- `/active-work`
- `/daily-logs`
- `/runbooks`
- `/inbox`
- `/inbox/new`
- `/inbox/bugs`
- `/inbox/features`
- `/inbox/support`
- `/inbox/closed`
- `/decisions`
- `/release-notes`
- `/ideas`
- `/view/<path:relative_path>`
- `/health`

## Systemd Example

See `deployment/worklog-dev.service.example`.

## Deployment Examples

- `deployment/worklog-dev.service.example`
- `deployment/nginx/worklog-dev.conf.example`
- `deployment/cloudflared/worklog-dev.example.yml`
