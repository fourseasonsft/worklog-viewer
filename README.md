# FSFT Worklog Viewer

Read-only Flask viewer for the FSFT worklog markdown repository.

## Purpose

- KB = how the platform works
- Worklog = what we did, what is next, bugs, features, support issues, and where we left off
- Codex should update the Worklog after meaningful work
- Codex should update the KB only when architecture, runbooks, infrastructure, auth, deployment, or business rules change

## Content Root

The viewer reads markdown from:

- `/opt/fsftdev/fsft-worklog`

## Start

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

The app listens on:

- `http://127.0.0.1:5075`

## Restart

```bash
pkill -f 'worklog-viewer/app.py' || true
python3 app.py
```

## Routes

- `/`
- `/roadmap`
- `/active-work`
- `/daily-logs`
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

See `worklog-dev.service.example`.
