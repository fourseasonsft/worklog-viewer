# FSFT Worklog Viewer

Read-only Flask viewer for the FSFT worklog markdown repository.

## Purpose

- KB = how the platform works
- Worklog = what we did, what is next, bugs, features, support issues, and where we left off
- Inbox = the active command transport between ChatGPT and Codex
- Codex should update the Worklog after meaningful work
- Codex should update the KB only when architecture, runbooks, infrastructure, auth, deployment, or business rules change
- Worklog is protected by Core/Unity SSO and restricted to Super Admin users only
- There is no local Worklog login, password store, or database
- Use the KB for workflow and platform guidance:
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/index.md`
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-overview.md`
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-daily-workflow.md`
  - `/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-viewer.md`
- The viewer is read-only but contains internal project information and must be protected before broad external exposure
- The long-term protection model is Core/Unity SSO, not a local Worklog login or separate identity system
- The dashboard is a daily command center with summary cards, top-priority docs, app status summaries, and recent inbox items

## Inbox Transport

- Inbox items are the active command queue.
- GitHub Issues are planning, discussion, and traceability.
- Worklog is engineering memory.
- KB is doctrine.
- Use `#/inbox <instruction-id>` to route a specific command packet through the Inbox transport.

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
- `/sso/launch`
- `/sso/callback`
- `/logout`
- `/view/<path:relative_path>`
- `/health`

## Dashboard Layout

- Summary cards for open bugs, open features, open support items, open new inbox items, active applications, and blockers
- Prominent `Current Focus`, `Next Actions`, and `Where We Left Off` sections
- Daily log visibility for the current day
- App status summary for Core, Unity, IMS, Dispatch, Parking, CY Storage, and Worklog
- Inbox summary with the newest items first

## Inbox Layout

- `/inbox` renders the operational inbox table with category and app/product filters
- `All` shows open items only and excludes `Closed`
- `Closed` shows only closed items
- Legacy `/inbox/new`, `/inbox/bugs`, `/inbox/features`, `/inbox/support`, and `/inbox/closed` routes now redirect to the table with the matching filter

## Systemd Example

See `deployment/worklog-dev.service.example`.

## Deployment Examples

- `deployment/worklog-dev.service.example`
- `deployment/nginx/worklog-dev.conf.example`
- `deployment/cloudflared/worklog-dev.example.yml`
