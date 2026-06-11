from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, render_template, request, url_for
import markdown


APP_ROOT = Path(__file__).resolve().parent
WORKLOG_ROOT = Path("/opt/fsftdev/fsft-worklog").resolve()

app = Flask(__name__)


def _resolve_worklog_path(relative_path: str) -> Path:
    candidate = (WORKLOG_ROOT / relative_path).resolve()
    if WORKLOG_ROOT not in candidate.parents and candidate != WORKLOG_ROOT:
        abort(404)
    if not candidate.exists() or not candidate.is_file():
        abort(404)
    return candidate


def _read_markdown(relative_path: str) -> str:
    return _resolve_worklog_path(relative_path).read_text(encoding="utf-8")


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=["extra", "tables", "fenced_code"])


def _latest_daily_log() -> str | None:
    daily_root = WORKLOG_ROOT / "01-daily-logs"
    candidates = sorted(daily_root.glob("*/*/*.md"))
    if not candidates:
        return None
    return str(candidates[-1].relative_to(WORKLOG_ROOT))


def _nav_items() -> list[dict[str, str]]:
    return [
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Roadmap", "endpoint": "roadmap"},
        {"label": "Active Work", "endpoint": "active_work"},
        {"label": "Daily Logs", "endpoint": "daily_logs"},
        {"label": "Inbox", "endpoint": "inbox"},
        {"label": "Inbox / New", "endpoint": "inbox_new"},
        {"label": "Decisions", "endpoint": "category_view", "category": "04-decisions"},
        {"label": "Release Notes", "endpoint": "category_view", "category": "05-release-notes"},
        {"label": "Ideas", "endpoint": "category_view", "category": "06-ideas"},
    ]


def _category_files(category: str) -> list[str]:
    root = WORKLOG_ROOT / category
    if not root.exists():
        return []
    return [str(path.relative_to(WORKLOG_ROOT)) for path in sorted(root.rglob("*.md"))]


def _pretty_title(path: str) -> str:
    mapping = {
        "ims.md": "IMS",
        "dispatch.md": "Dispatch",
        "parking.md": "Parking",
        "unity.md": "Unity",
        "core.md": "Core",
        "cy-storage.md": "CY Storage",
    }
    return mapping.get(Path(path).name, Path(path).stem.replace("-", " ").title())


@app.context_processor
def inject_globals() -> dict[str, object]:
    return {
        "nav_items": _nav_items(),
        "content_root": str(WORKLOG_ROOT),
        "now_utc": datetime.now(timezone.utc),
    }


@app.route("/")
def dashboard():
    cards = [
        {
            "title": "Current Focus",
            "path": "00-dashboard/current-focus.md",
        },
        {
            "title": "Where We Left Off",
            "path": "00-dashboard/where-we-left-off.md",
        },
        {
            "title": "Blockers",
            "path": "00-dashboard/blockers.md",
        },
        {
            "title": "Next Actions",
            "path": "00-dashboard/next-actions.md",
        },
        {
            "title": "Today’s Daily Log",
            "path": _latest_daily_log() or "01-daily-logs/2026/06/2026-06-11.md",
        },
        {
            "title": "Inbox / New Items",
            "path": "04-inbox/new/example-inbox-item.md",
        },
    ]
    rendered = []
    for card in cards:
        source = _read_markdown(card["path"])
        rendered.append({**card, "html": _render_markdown(source)})
    return render_template("dashboard.html", cards=rendered)


@app.route("/roadmap")
def roadmap():
    files = [
        "02-roadmap/platform-roadmap.md",
        "02-roadmap/core-roadmap.md",
        "02-roadmap/unity-roadmap.md",
        "02-roadmap/ims-roadmap.md",
        "02-roadmap/dispatch-roadmap.md",
        "02-roadmap/cy-storage-roadmap.md",
        "02-roadmap/parking-roadmap.md",
    ]
    sections = [{"path": path, "title": _pretty_title(path), "html": _render_markdown(_read_markdown(path))} for path in files]
    return render_template("section.html", title="Roadmap", sections=sections)


@app.route("/active-work")
def active_work():
    files = [
        "03-active-work/ims.md",
        "03-active-work/dispatch.md",
        "03-active-work/parking.md",
        "03-active-work/unity.md",
        "03-active-work/core.md",
        "03-active-work/cy-storage.md",
    ]
    sections = [{"path": path, "title": _pretty_title(path), "html": _render_markdown(_read_markdown(path))} for path in files]
    return render_template("section.html", title="Active Work", sections=sections)


@app.route("/daily-logs")
def daily_logs():
    logs = [str(path.relative_to(WORKLOG_ROOT)) for path in sorted((WORKLOG_ROOT / "01-daily-logs").glob("*/*/*.md"), reverse=True)]
    return render_template("listing.html", title="Daily Logs", items=logs)


@app.route("/decisions")
def decisions():
    return render_template("listing.html", title="Decisions", items=_category_files("04-decisions"))


@app.route("/release-notes")
def release_notes():
    return render_template("listing.html", title="Release Notes", items=_category_files("05-release-notes"))


@app.route("/ideas")
def ideas():
    return render_template("listing.html", title="Ideas", items=_category_files("06-ideas"))


@app.route("/inbox")
def inbox():
    items = [
        "04-inbox/new/example-inbox-item.md",
        *sorted(str(path.relative_to(WORKLOG_ROOT)) for path in (WORKLOG_ROOT / "04-inbox/triaged").glob("*.md")),
        *sorted(str(path.relative_to(WORKLOG_ROOT)) for path in (WORKLOG_ROOT / "04-inbox/bugs").glob("*.md")),
        *sorted(str(path.relative_to(WORKLOG_ROOT)) for path in (WORKLOG_ROOT / "04-inbox/features").glob("*.md")),
        *sorted(str(path.relative_to(WORKLOG_ROOT)) for path in (WORKLOG_ROOT / "04-inbox/support").glob("*.md")),
        *sorted(str(path.relative_to(WORKLOG_ROOT)) for path in (WORKLOG_ROOT / "04-inbox/closed").glob("*.md")),
    ]
    return render_template("listing.html", title="Inbox", items=items)


@app.route("/inbox/new")
def inbox_new():
    return render_template("listing.html", title="Inbox / New", items=_category_files("04-inbox/new"))


@app.route("/inbox/bugs")
def inbox_bugs():
    return render_template("listing.html", title="Inbox / Bugs", items=_category_files("04-inbox/bugs"))


@app.route("/inbox/features")
def inbox_features():
    return render_template("listing.html", title="Inbox / Features", items=_category_files("04-inbox/features"))


@app.route("/inbox/support")
def inbox_support():
    return render_template("listing.html", title="Inbox / Support", items=_category_files("04-inbox/support"))


@app.route("/inbox/closed")
def inbox_closed():
    return render_template("listing.html", title="Inbox / Closed", items=_category_files("04-inbox/closed"))


@app.route("/view/<path:relative_path>")
def view_file(relative_path: str):
    source = _read_markdown(relative_path)
    return render_template(
        "document.html",
        title=Path(relative_path).name,
        relative_path=relative_path,
        html=_render_markdown(source),
    )


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/category/<path:category>")
def category_view(category: str):
    files = _category_files(category)
    if not files:
        abort(404)
    return render_template("listing.html", title=category.replace("-", " ").title(), items=files)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5075, debug=False)
