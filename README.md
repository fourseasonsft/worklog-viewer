# FSFT Worklog Viewer

Read-only Flask viewer for the FSFT worklog markdown repository.

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
- `/decisions`
- `/release-notes`
- `/ideas`
- `/view/<path:relative_path>`
- `/health`

## Systemd Example

See `worklog-dev.service.example`.

