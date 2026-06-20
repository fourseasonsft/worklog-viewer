from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urljoin

from flask import Flask, abort, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import markdown


APP_ROOT = Path(__file__).resolve().parent
WORKLOG_ROOT = Path("/opt/fsftdev/fsft-worklog").resolve()
WORKLOG_SESSION_KEY = "worklog_auth"
WORKLOG_APPLICATION_KEY = "worklog"
DEFAULT_UNITY_BASE_URL = "https://unity.fsftdev.com"
ASSERTION_VERSION = 1
ASSERTION_TYPE = "core_application_assertion"
ASSERTION_ISSUER = "four-seasons-core"
CORE_SERVICE_OVERRIDE_PATHS = (
    Path("/etc/systemd/system/employees.service.d/override.conf"),
    Path("/etc/systemd/system/employees.service"),
)
ACTIVE_WORK_FILES = [
    {"title": "Core", "path": "03-active-work/core.md"},
    {"title": "Unity", "path": "03-active-work/unity.md"},
    {"title": "IMS", "path": "03-active-work/ims.md"},
    {"title": "Dispatch", "path": "03-active-work/dispatch.md"},
    {"title": "Parking", "path": "03-active-work/parking.md"},
    {"title": "CY Storage", "path": "03-active-work/cy-storage.md"},
    {"title": "Hiring", "path": "03-active-work/hiring.md"},
    {"title": "Worklog", "path": "03-active-work/worklog.md"},
]
TOP_DASHBOARD_FILES = [
    {"title": "Portfolio Status", "path": "00-dashboard/portfolio-status.md", "anchor": "portfolio-status"},
    {"title": "Engineering Priorities", "path": "00-dashboard/engineering-priorities.md", "anchor": "engineering-priorities"},
    {"title": "Current Focus", "path": "00-dashboard/current-focus.md", "anchor": "current-focus"},
    {"title": "Next Actions", "path": "00-dashboard/next-actions.md", "anchor": "next-actions"},
    {"title": "Where We Left Off", "path": "00-dashboard/where-we-left-off.md", "anchor": "where-we-left-off"},
]
INBOX_FOLDERS = ["new", "bugs", "features", "support"]
THOUGHT_BOX_DIR = WORKLOG_ROOT / "04-inbox/thought-box"
INTAKE_TYPE_BUCKETS = {
    "bug": "bugs",
    "feature": "features",
    "support": "support",
    "note": "new",
    "blocker": "new",
    "thought": "new",
    "customer-request": "new",
}
APP_FILTERS = {
    "core": "Core",
    "unity": "Unity",
    "ims": "IMS",
    "cy-storage": "CY Storage",
    "dispatch": "Dispatch",
    "parking": "Parking",
    "hiring": "Hiring",
    "worklog": "Worklog",
}
INBOX_TYPES = {
    "all",
    "new",
    "bugs",
    "features",
    "support",
    "closed",
}


app = Flask(__name__)
app.secret_key = (
    os.environ.get("WORKLOG_SECRET_KEY", "").strip()
    or os.environ.get("SECRET_KEY", "").strip()
    or "worklog-dev-secret"
)
app.config["WORKLOG_ASSERTION_SECRET"] = (
    os.environ.get("WORKLOG_ASSERTION_SECRET", "").strip()
    or os.environ.get("CORE_ASSERTION_SECRET", "").strip()
    or "worklog-dev-assertion-secret"
)
app.config["WORKLOG_ASSERTION_SALT"] = (
    os.environ.get("WORKLOG_ASSERTION_SALT", "").strip()
    or "external-app-assertion-v1"
)
app.config["WORKLOG_ASSERTION_MAX_AGE_SECONDS"] = int(
    os.environ.get("WORKLOG_ASSERTION_MAX_AGE_SECONDS", "300")
)
app.config["UNITY_BASE_URL"] = (
    os.environ.get("UNITY_BASE_URL", "").strip().rstrip("/")
    or DEFAULT_UNITY_BASE_URL
)
app.config["OPENAI_API_KEY"] = os.environ.get("OPENAI_API_KEY", "").strip()


def _read_core_assertion_secret_from_system() -> str | None:
    for path in CORE_SERVICE_OVERRIDE_PATHS:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        for line in text.splitlines():
            if "CORE_ASSERTION_SECRET=" not in line:
                continue
            match = re.search(r"CORE_ASSERTION_SECRET=([^\s\"]+)", line)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    return candidate
    return None


if app.config["WORKLOG_ASSERTION_SECRET"] == "worklog-dev-assertion-secret":
    system_secret = _read_core_assertion_secret_from_system()
    if system_secret:
        app.config["WORKLOG_ASSERTION_SECRET"] = system_secret


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
        {
            "label": "Primary",
            "items": [
                {"label": "Dashboard", "endpoint": "dashboard"},
                {"label": "Idea Inventory", "endpoint": "assistant"},
                {"label": "Updates", "endpoint": "release_notes"},
                {"label": "Inbox", "endpoint": "inbox"},
                {"label": "Daily Log", "endpoint": "daily_logs"},
            ],
        },
        {
            "label": "More",
            "items": [
                {"label": "Structured Intake", "endpoint": "intake"},
                {"label": "Portfolio Status", "endpoint": "view_file", "args": {"relative_path": "00-dashboard/portfolio-status.md"}},
                {"label": "Engineering Priorities", "endpoint": "view_file", "args": {"relative_path": "00-dashboard/engineering-priorities.md"}},
                {"label": "Roadmap", "endpoint": "roadmap"},
                {"label": "Active Work", "endpoint": "active_work"},
                {"label": "Runbooks", "endpoint": "runbooks"},
                {"label": "Decisions", "endpoint": "decisions"},
                {"label": "Release Notes", "endpoint": "release_notes"},
                {"label": "Ideas", "endpoint": "ideas"},
                {"label": "Inbox / New", "endpoint": "inbox_new"},
                {"label": "Inbox / Bugs", "endpoint": "inbox_bugs"},
                {"label": "Inbox / Features", "endpoint": "inbox_features"},
                {"label": "Inbox / Support", "endpoint": "inbox_support"},
                {"label": "Inbox / Closed", "endpoint": "inbox_closed"},
            ],
        },
    ]


def _category_files(category: str) -> list[str]:
    root = WORKLOG_ROOT / category
    if not root.exists():
        return []
    return [str(path.relative_to(WORKLOG_ROOT)) for path in sorted(root.rglob("*.md"))]


def _relative_md_files(relative_dir: str) -> list[Path]:
    root = WORKLOG_ROOT / relative_dir
    if not root.exists():
        return []
    return [path for path in sorted(root.rglob("*.md")) if path.is_file()]


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _format_file_timestamp(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return "Unknown"


def _extract_section_text(markdown_text: str, heading: str) -> str:
    heading = heading.strip().lower()
    collecting = False
    collected: list[str] = []
    for line in markdown_text.splitlines():
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match:
            current_heading = heading_match.group(1).strip().lower()
            if collecting and current_heading != heading:
                break
            collecting = current_heading == heading
            continue
        if collecting:
            collected.append(line)
    return "\n".join(collected).strip()


def _extract_first_value(section_text: str) -> str:
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s*", "", line).strip()
        if line:
            return line
    return ""


def _count_meaningful_bullets(section_text: str) -> int:
    bullets = []
    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item:
                bullets.append(item)
    if not bullets:
        return 0

    meaningful = [
        item
        for item in bullets
        if not re.match(r"^(none|no\b|none recorded\b|none at the moment\b|none currently\b|none at the application layer\b|none blocking\b)", item.lower())
    ]
    return len(meaningful)


def _count_markdown_files(relative_dir: str) -> int:
    return len(_relative_md_files(relative_dir))


def _parse_key_value_metadata(markdown_text: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        if ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            metadata[key] = value
    return metadata


def _section_key_value_metadata(markdown_text: str, section_heading: str) -> dict[str, str]:
    section_text = _extract_section_text(markdown_text, section_heading)
    return _parse_key_value_metadata(section_text)


def _normalize_percent(value: str | None) -> str:
    if not value:
        return ""
    candidate = value.strip()
    return candidate if re.fullmatch(r"\d{1,3}%?", candidate) else ""


def _slugify_app_name(value: str) -> str:
    value = value.lower().replace("&", " and ")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-")


def _normalize_app_filter(value: str | None) -> str:
    if not value:
        return "all"
    slug = _slugify_app_name(value)
    if slug in APP_FILTERS or slug == "other":
        return slug
    if value.strip().lower() in {"all", "all-apps", "all apps"}:
        return "all"
    return "other"


def _parse_active_work_file(relative_path: str, title: str) -> dict[str, object]:
    source_path = WORKLOG_ROOT / relative_path
    text = source_path.read_text(encoding="utf-8")
    current_sprint = _section_key_value_metadata(text, "Current Sprint")
    legacy_current_focus = _extract_section_text(text, "Current Sprint / Focus")
    if not current_sprint:
        current_sprint = {}

    last_sprint = _section_key_value_metadata(text, "Last Sprint")
    next_sprint = _section_key_value_metadata(text, "Next Suggested Sprint")
    blockers_text = _extract_section_text(text, "Blockers")
    last_updated_text = _extract_section_text(text, "Last Updated")
    last_updated = _extract_first_value(last_updated_text) or _format_file_timestamp(source_path)
    current_name = current_sprint.get("name") or current_sprint.get("focus") or current_sprint.get("objective") or ""
    percent_complete = _normalize_percent(current_sprint.get("percent complete") or current_sprint.get("percent"))
    status = (current_sprint.get("status") or "").strip().title()
    if not current_name or status.lower() not in {"active", "planned", "paused", "stable", "blocked"}:
        current_name = ""
        percent_complete = ""
        status = "Stable" if title in {"Core", "Unity", "Worklog"} else (status or "Stable")
    sprint_notes = current_sprint.get("notes") or current_sprint.get("summary") or legacy_current_focus
    last_sprint_name = last_sprint.get("name") or last_sprint.get("completed") or ""
    next_sprint_name = next_sprint.get("name") or next_sprint.get("why") or ""
    inbox_items = _related_inbox_items(title)
    return {
        "title": title,
        "path": relative_path,
        "current_sprint_name": current_name,
        "current_sprint_status": status,
        "current_sprint_percent": percent_complete,
        "current_sprint_notes": sprint_notes,
        "last_sprint_name": last_sprint_name,
        "last_sprint_completed": last_sprint.get("completed") or "",
        "last_sprint_outcome": last_sprint.get("outcome") or "",
        "next_suggested_sprint_name": next_sprint_name,
        "next_suggested_sprint_why": next_sprint.get("why") or "",
        "next_suggested_sprint_first_step": next_sprint.get("suggested_first_step") or "",
        "current_sprint_html": _render_markdown(sprint_notes or "_No current sprint recorded._"),
        "blockers_count": _count_meaningful_bullets(blockers_text),
        "last_updated": last_updated,
        "inbox_items": inbox_items,
        "has_active_sprint": bool(current_name),
    }


def _parse_inbox_item(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    metadata = _parse_key_value_metadata(text)
    summary = (
        metadata.get("summary")
        or metadata.get("description")
        or metadata.get("notes")
        or metadata.get("title")
        or path.stem.replace("-", " ").title()
    )
    detail_lines = []
    for field in ("app", "priority", "status", "type", "next action"):
        value = metadata.get(field)
        if value:
            detail_lines.append((field.title(), value))
    excerpt = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if not line:
            continue
        excerpt.append(line)
        if len(excerpt) >= 3:
            break
    return {
        "title": summary,
        "path": str(path.relative_to(WORKLOG_ROOT)),
        "category": path.parent.name,
        "metadata": detail_lines,
        "excerpt_html": _render_markdown("\n\n".join(excerpt) if excerpt else "_No details recorded._"),
        "mtime": _file_mtime(path),
        "mtime_display": _format_file_timestamp(path),
    }


def _infer_inbox_app(path: Path, metadata: dict[str, str], text: str) -> str:
    candidates = [
        metadata.get("app/project"),
        metadata.get("app_project"),
        metadata.get("app"),
        metadata.get("product"),
        metadata.get("project"),
    ]
    for candidate in candidates:
        if candidate:
            slug = _normalize_app_filter(candidate)
            if slug != "other" and slug != "all":
                return slug

    stem = path.stem.lower()
    for slug in APP_FILTERS:
        if slug in stem:
            return slug

    haystack = f"{path.as_posix().lower()} {text.lower()}"
    for slug, label in APP_FILTERS.items():
        if slug in haystack or label.lower() in haystack:
            return slug
    return "other"


def _parse_inbox_queue_item(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    metadata = _parse_key_value_metadata(text)
    structured = _parse_structured_inbox_item(path)
    title = structured.get("title") or path.stem.replace("-", " ").title()
    item_type = path.parent.name
    status = metadata.get("status") or "Open"
    priority = metadata.get("priority") or "medium"
    source = metadata.get("source") or "Worklog Viewer"
    app_slug = _infer_inbox_app(path, metadata, text)
    app_label = APP_FILTERS.get(app_slug, metadata.get("app/project") or metadata.get("app") or "Unassigned")
    created = metadata.get("created") or metadata.get("created date") or metadata.get("created_at") or ""
    updated = metadata.get("updated") or metadata.get("updated_at") or metadata.get("last updated") or ""
    created_updated = created or updated or _format_file_timestamp(path)
    description = (
        metadata.get("summary")
        or metadata.get("description")
        or metadata.get("notes")
        or metadata.get("plain_english_summary")
        or metadata.get("technical_notes")
        or structured.get("summary")
        or title
    )
    return {
        "type": item_type,
        "title": title,
        "app_slug": app_slug,
        "app_label": app_label if app_label else "Unassigned",
        "priority": priority,
        "status": status,
        "created_updated": created_updated,
        "source": source,
        "path": str(path.relative_to(WORKLOG_ROOT)),
        "category": path.parent.name,
        "mtime": _file_mtime(path),
        "mtime_display": _format_file_timestamp(path),
        "summary": description,
    }


def _parse_structured_inbox_item(path: Path) -> dict[str, str]:
    data: dict[str, str] = {"path": str(path.relative_to(WORKLOG_ROOT))}
    text = path.read_text(encoding="utf-8")
    current_section = None
    for line in text.splitlines():
        if line.startswith("- "):
            if ":" in line[2:]:
                key, value = line[2:].split(":", 1)
                data[key.strip().lower().replace(" ", "_")] = value.strip()
        elif line.startswith("## "):
            current_section = line[3:].strip().lower().replace(" ", "_")
            data.setdefault(current_section, "")
        elif current_section and line.strip():
            data[current_section] = (data.get(current_section, "") + "\n" + line).strip()
    data["title"] = data.get("title") or path.stem.replace("-", " ").title()
    data["category"] = path.parent.name
    data["summary"] = data.get("plain_english_summary") or data.get("summary") or data["title"]
    data["next_action"] = data.get("suggested_next_action") or data.get("next_action") or ""
    data["mtime_display"] = _format_file_timestamp(path)
    data["mtime"] = _file_mtime(path)
    data["why_it_matters"] = data.get("why_it_matters") or "Tracked intake item."
    return data


def _dashboard_counts() -> dict[str, int]:
    active_work_count = len(ACTIVE_WORK_FILES)
    blockers = _count_meaningful_bullets(_read_markdown("00-dashboard/blockers.md"))
    for item in ACTIVE_WORK_FILES:
        source_path = WORKLOG_ROOT / item["path"]
        text = source_path.read_text(encoding="utf-8")
        blockers += _count_meaningful_bullets(_extract_section_text(text, "Blockers"))
    return {
        "open_bugs": _count_markdown_files("04-inbox/bugs"),
        "open_features": _count_markdown_files("04-inbox/features"),
        "open_support": _count_markdown_files("04-inbox/support"),
        "open_new": _count_markdown_files("04-inbox/new"),
        "active_applications": active_work_count,
        "blockers": blockers,
    }


def _filter_inbox_queue_items(items: list[dict[str, object]], inbox_type: str, app_slug: str) -> list[dict[str, object]]:
    inbox_type = inbox_type.lower()
    app_slug = _normalize_app_filter(app_slug)
    if inbox_type == "closed":
        visible_types = {"closed"}
    elif inbox_type in {"bugs", "features", "support", "new"}:
        visible_types = {inbox_type}
    else:
        visible_types = {"new", "bugs", "features", "support"}
    filtered = [item for item in items if item["type"] in visible_types]
    if app_slug != "all":
        filtered = [item for item in filtered if item["app_slug"] == app_slug]
    return filtered


def _recent_inbox_items(limit: int = 8) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for folder in INBOX_FOLDERS:
        for path in _relative_md_files(f"04-inbox/{folder}"):
            items.append(_parse_inbox_item(path))
    items.sort(key=lambda item: (item["mtime"], item["path"]), reverse=True)
    return items[:limit]


def _all_structured_inbox_items() -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for folder in INBOX_FOLDERS:
        for path in _relative_md_files(f"04-inbox/{folder}"):
            items.append(_parse_structured_inbox_item(path))
    items.sort(key=lambda item: (item.get("mtime", 0), item["path"]), reverse=True)
    return items


def _inbox_queue_items() -> list[dict[str, object]]:
    items = []
    for folder in ["new", "bugs", "features", "support", "closed"]:
        for path in _relative_md_files(f"04-inbox/{folder}"):
            items.append(_parse_inbox_queue_item(path))
    items.sort(key=lambda item: (item["mtime"], item["path"]), reverse=True)
    return items


def _related_inbox_items(app_title: str) -> list[dict[str, str]]:
    app_title_lower = app_title.lower()
    matches = []
    for item in _all_structured_inbox_items():
        haystack = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("summary", "")),
                str(item.get("app_project", "")),
                str(item.get("type", "")),
            ]
        ).lower()
        if app_title_lower in haystack:
            matches.append(item)
    return matches[:3]


def _dashboard_intake_counts() -> dict[str, int]:
    return {
        "total": sum(_count_markdown_files(f"04-inbox/{folder}") for folder in INBOX_FOLDERS),
        "urgent_high": sum(
            1
            for item in _all_structured_inbox_items()
            if str(item.get("priority", "")).lower() in {"urgent", "high"}
        ),
        "blockers": sum(
            1
            for item in _all_structured_inbox_items()
            if "block" in str(item.get("type", "")).lower() or "block" in str(item.get("status", "")).lower()
        ),
        "bugs": _count_markdown_files("04-inbox/bugs"),
        "features": _count_markdown_files("04-inbox/features"),
        "support": _count_markdown_files("04-inbox/support"),
        "new": _count_markdown_files("04-inbox/new"),
    }


def _slugify_title(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "intake-item"


def _create_inbox_item_from_form(form: dict[str, str]) -> Path:
    title = (form.get("title") or "").strip() or "Untitled Worklog Item"
    item_type = (form.get("type") or "note").strip().lower()
    bucket = INTAKE_TYPE_BUCKETS.get(item_type, "new")
    created_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{created_date}-{_slugify_title(title)}.md"
    target = WORKLOG_ROOT / f"04-inbox/{bucket}/{filename}"
    target.parent.mkdir(parents=True, exist_ok=True)

    plain_summary = (form.get("plain_english_summary") or "").strip()
    technical_notes = (form.get("technical_notes") or "").strip()
    next_action = (form.get("next_action") or "").strip()
    source = (form.get("source") or "").strip() or "Worklog Viewer"
    requested_by = (form.get("requested_by") or "").strip() or "David"
    app_project = (form.get("app_project") or "").strip() or "worklog"
    priority = (form.get("priority") or "medium").strip().lower() or "medium"
    why_it_matters = {
        "bug": "This blocks reliable operation or creates user friction.",
        "feature": "This adds capability that supports the Worklog workflow.",
        "support": "This keeps the Worklog usable and reduces operational overhead.",
    }.get(item_type, "This is useful intake that should be tracked until triaged.")

    content = "\n".join(
        [
            f"# {title}",
            "",
            f"- Type: {item_type}",
            f"- App/Project: {app_project}",
            f"- Priority: {priority}",
            f"- Status: new",
            f"- Created Date: {created_date}",
            f"- Source: {source}",
            f"- Requested By: {requested_by}",
            "",
            "## Plain English Summary",
            plain_summary or "TBD",
            "",
            "## Why It Matters",
            why_it_matters,
            "",
            "## Technical Notes",
            technical_notes or "TBD",
            "",
            "## Suggested Next Action",
            next_action or "TBD",
            "",
        ]
    )
    target.write_text(content, encoding="utf-8")
    return target


def _intake_plain_mode_enabled() -> bool:
    return request.args.get("plain", "").strip() == "1"


def _ensure_thought_box_dir() -> None:
    THOUGHT_BOX_DIR.mkdir(parents=True, exist_ok=True)
    _thought_digested_dir().mkdir(parents=True, exist_ok=True)
    _thought_archived_dir().mkdir(parents=True, exist_ok=True)
    _assistant_update_shipments_dir().mkdir(parents=True, exist_ok=True)


def _thought_digested_dir() -> Path:
    return THOUGHT_BOX_DIR / "digested"


def _thought_archived_dir() -> Path:
    return THOUGHT_BOX_DIR / "archived"


def _assistant_update_shipments_dir() -> Path:
    return WORKLOG_ROOT / "05-release-notes/assistant-update-shipments"


def _slugify_title(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "thought"


def _thought_path_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")


def _parse_thought_file(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    data: dict[str, str] = {"path": str(path.relative_to(WORKLOG_ROOT))}
    current = None
    for line in text.splitlines():
        if line.startswith("- "):
            if ":" in line[2:]:
                key, value = line[2:].split(":", 1)
                data[key.strip().lower().replace(" ", "_")] = value.strip()
        elif line.startswith("## "):
            current = line[3:].strip().lower().replace(" ", "_")
            data.setdefault(current, "")
        elif current and line.strip():
            data[current] = (data.get(current, "") + "\n" + line).strip()
    data["title"] = data.get("title") or path.stem.replace("-", " ").title()
    data["raw_text"] = data.get("raw_text") or data.get("raw") or ""
    return data


def _thought_box_items(digested_only: bool | None = None) -> list[dict[str, str]]:
    _ensure_thought_box_dir()
    items: list[dict[str, str]] = []
    for path in sorted(THOUGHT_BOX_DIR.glob("*.md"), reverse=True):
        item = _parse_thought_file(path)
        if digested_only is True and item.get("digest_status") == "not_digested":
            continue
        if digested_only is False and item.get("digest_status") != "not_digested":
            continue
        items.append(item)
    return items


def _move_thought(path: Path, destination_dir: Path) -> Path:
    _ensure_thought_box_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    shutil.move(str(path), str(destination))
    return destination


def _thought_item_fingerprint(item: dict[str, str]) -> str:
    return item.get("thought_fingerprint") or hashlib.sha256(item.get("raw_text", "").strip().encode("utf-8")).hexdigest()[:16]


def _worklog_item_filename(title: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{_slugify_title(title)}.md"


def _render_worklog_item(item: dict[str, object], source_thoughts: list[str]) -> str:
    return "\n".join(
        [
            f"# {item['title']}",
            "",
            f"- Type: {item['type']}",
            f"- App/Project: {item['app_project']}",
            f"- Priority: {item['priority']}",
            f"- Status: new",
            f"- Created At: {datetime.now(timezone.utc).isoformat()}",
            f"- Source Thought(s): {', '.join(source_thoughts)}",
            "",
            "## Plain English Summary",
            str(item.get("plain_english_summary") or "TBD"),
            "",
            "## Why It Matters",
            {
                "bug": "This blocks reliable operation or creates user friction.",
                "feature": "This adds capability that supports the Worklog workflow.",
                "support": "This keeps the Worklog usable and reduces operational overhead.",
            }.get(str(item["type"]), "This is a tracked follow-up from the assistant."),
            "",
            "## Suggested Next Action",
            str(item.get("suggested_next_action") or "TBD"),
            "",
            "## Source Thought(s)",
            *[f"- {ref}" for ref in source_thoughts],
            "",
        ]
    )


def _create_worklog_item_from_proposal(item: dict[str, object]) -> Path:
    destination = WORKLOG_ROOT / str(item["destination_folder"])
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / _worklog_item_filename(str(item["title"]))
    path.write_text(_render_worklog_item(item, [str(ref) for ref in item.get("source_thoughts", [])]), encoding="utf-8")
    return path


def _thoughts_by_paths(paths: list[str]) -> list[dict[str, str]]:
    wanted = set(paths)
    items = []
    for item in _thought_box_items(digested_only=False):
        if item.get("path") in wanted:
            items.append(item)
    return items


def _digest_groups_from_items(items: list[dict[str, str]]) -> dict[str, object]:
    preview = _digest_preview(items)
    proposals = preview.get("proposed_items", [])
    seen = set()
    deduped = []
    for proposal in proposals:
        key = (
            proposal.get("title"),
            proposal.get("destination_folder"),
            proposal.get("app_project"),
            proposal.get("type"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(proposal)
    preview["proposed_items"] = deduped
    preview["digest_id"] = hashlib.sha256(
        json.dumps([item.get("path") for item in items], sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    preview["source_thoughts"] = [item.get("path") for item in items]
    preview["update_bundle_title"] = "Worklog Idea Update"
    preview["update_status"] = "proposed"
    return preview


def _assistant_update_shipments() -> list[dict[str, str]]:
    _ensure_thought_box_dir()
    shipments: list[dict[str, str]] = []
    for path in sorted(_assistant_update_shipments_dir().glob("*.md"), reverse=True):
        text = path.read_text(encoding="utf-8")
        shipments.append(
            {
                "path": str(path.relative_to(WORKLOG_ROOT)),
                "title": path.stem.replace("-", " ").title(),
                "excerpt": _first_nonempty_paragraph(text) or "Shipped update.",
                "mtime_display": _format_file_timestamp(path),
            }
        )
    return shipments


def _write_update_shipment_record(preview: dict[str, object], created_items: list[str], moved_paths: list[str]) -> Path:
    _assistant_update_shipments_dir().mkdir(parents=True, exist_ok=True)
    title = str(preview.get("update_bundle_title") or "Worklog Idea Update")
    path = _assistant_update_shipments_dir() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{_slugify_title(title)}.md"
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"- status: shipped/live",
                f"- created_at: {datetime.now(timezone.utc).isoformat()}",
                f"- source_thought_count: {len(preview.get('source_thoughts', []))}",
                f"- created_work_items: {len(created_items)}",
                f"- created_items: {', '.join(created_items) if created_items else 'None'}",
                "",
                "## Summary",
                str(preview.get("plain_summary") or "Approved and routed Worklog update."),
                "",
                "## Routed Work Items",
                *([f"- {item}" for item in created_items] or ["- None"]),
                "",
                "## Source Ideas",
                *([f"- {item}" for item in moved_paths] or ["- None"]),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_thought_file(raw_text: str) -> Path:
    _ensure_thought_box_dir()
    prefix = _thought_path_prefix()
    slug = _slugify_title(raw_text[:48])
    path = THOUGHT_BOX_DIR / f"{prefix}-{slug}.md"
    title = raw_text.strip().splitlines()[0][:80] if raw_text.strip() else "Thought"
    inferred = _infer_thought(raw_text)
    fingerprint = hashlib.sha256(raw_text.strip().encode("utf-8")).hexdigest()[:16]
    content = "\n".join(
        [
            f"# {title}",
            "",
            f"- created_at: {datetime.now(timezone.utc).isoformat()}",
            "- source: David",
            "- status: raw",
            "- digest_status: not_digested",
            f"- thought_fingerprint: {fingerprint}",
            f"- raw_text: {raw_text.strip()}",
            f"- ai_inferred_app: {inferred['ai_inferred_app']}",
            f"- ai_inferred_type: {inferred['ai_inferred_type']}",
            f"- ai_summary: {inferred['ai_summary']}",
            "",
            "## Raw Thought",
            raw_text.strip() or "TBD",
            "",
        ]
    )
    path.write_text(content, encoding="utf-8")
    return path


def _kb_reference_text() -> str:
    sections = []
    for path in [
        WORKLOG_ROOT / "00-dashboard/current-focus.md",
        WORKLOG_ROOT / "00-dashboard/next-actions.md",
        WORKLOG_ROOT / "00-dashboard/where-we-left-off.md",
        WORKLOG_ROOT / "03-active-work/worklog.md",
        WORKLOG_ROOT / "03-active-work/ims.md",
        WORKLOG_ROOT / "03-active-work/dispatch.md",
        WORKLOG_ROOT / "03-active-work/cy-storage.md",
        Path("/opt/fsftdev/fsft-knowledge-base/07-worklog/index.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-overview.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/07-worklog/worklog-viewer.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/03-ims/index.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/05-dispatch/index.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/04-cy-storage/index.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/01-core/index.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/02-unity/index.md"),
        Path("/opt/fsftdev/fsft-knowledge-base/20-xalan/index.md"),
    ]:
        if path.exists():
            try:
                sections.append(f"## {path.name}\n\n{path.read_text(encoding='utf-8')[:4000]}")
            except OSError:
                continue
    return "\n\n".join(sections)


def _openai_available() -> bool:
    return bool(app.config.get("OPENAI_API_KEY"))


def _safe_openai_error() -> str:
    return "OpenAI is not configured. Set OPENAI_API_KEY in the environment to enable assistant digestion."


def _call_openai_digest(items: list[dict[str, str]]) -> dict[str, object] | None:
    api_key = app.config.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    prompt = "\n".join(
        [
            "You are the FSFT Worklog Assistant.",
            "Use only the provided Worklog and KB context.",
            "Summarize the raw thoughts and propose Worklog inbox items plus a Codex prompt.",
            "Return JSON with keys plain_summary, grouped_by_app, likely_bugs, likely_features, likely_blockers, recommended_worklog_items, recommended_codex_prompt.",
            "Do not recommend moving or deleting files in preview mode.",
        ]
    )
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5.1"),
        "input": [
            {"role": "system", "content": [{"type": "text", "text": prompt}]},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "thoughts": items,
                                "reference_material": _kb_reference_text()[:12000],
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }
    request_obj = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_obj, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    output_text = ""
    for part in data.get("output", []):
        for content in part.get("content", []):
            if content.get("type") == "output_text":
                output_text += content.get("text", "")
    if not output_text:
        return None
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _infer_thought(raw_text: str) -> dict[str, str]:
    text = raw_text.lower()
    app_guess = ""
    app_labels = {
        "ims": "IMS",
        "dispatch": "Dispatch",
        "cy storage": "CY Storage",
        "core": "Core",
        "unity": "Unity",
        "parking": "Parking",
        "hiring": "Hiring",
        "worklog": "Worklog",
    }
    for candidate, label in app_labels.items():
        if candidate in text:
            app_guess = label
            break
    type_guess = ""
    if any(word in text for word in ["feature", "request", "add", "should", "would like", "break bulk"]):
        type_guess = "feature"
    elif any(word in text for word in ["bug", "broken", "error", "fail", "issue"]):
        type_guess = "bug"
    elif any(word in text for word in ["block", "blocked", "can't", "cannot", "need"]):
        type_guess = "blocker"
    elif any(word in text for word in ["support", "help", "question"]):
        type_guess = "support"
    else:
        type_guess = "thought"
    return {
        "ai_inferred_app": app_guess,
        "ai_inferred_type": type_guess,
        "ai_summary": raw_text.strip()[:220],
    }


def _digest_preview(items: list[dict[str, str]]) -> dict[str, object]:
    openai_preview = _call_openai_digest(items)
    if openai_preview:
        openai_preview["kb_context_excerpt"] = _kb_reference_text()[:6000]
        return openai_preview
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in items:
        raw = item.get("raw_text", "")
        inferred = _infer_thought(raw)
        key = inferred["ai_inferred_app"] or "Unclear"
        grouped[key].append({**item, **inferred})

    proposed_items: list[dict[str, object]] = []
    for app_name, group in grouped.items():
        by_type: dict[str, list[dict[str, str]]] = defaultdict(list)
        for thought in group:
            by_type[thought.get("ai_inferred_type") or "thought"].append(thought)
        for inferred_type, thoughts in by_type.items():
            if inferred_type == "thought" and len(thoughts) == 1:
                continue
            source_refs = [thought["path"] for thought in thoughts]
            combined_text = " ".join(thought.get("raw_text", "") for thought in thoughts).strip()
            title = f"{app_name} {inferred_type.title()} follow-up".strip()
            destination = {
                "bug": "04-inbox/bugs",
                "feature": "04-inbox/features",
                "support": "04-inbox/support",
                "blocker": "04-inbox/new",
                "thought": "04-inbox/new",
            }.get(inferred_type, "04-inbox/new")
            priority = "high" if inferred_type in {"bug", "blocker"} else "medium"
            proposed_items.append(
                {
                    "title": title,
                    "destination_folder": destination,
                    "type": inferred_type if inferred_type in {"bug", "feature", "support"} else "note",
                    "app_project": app_name or "worklog",
                    "priority": priority,
                    "plain_english_summary": combined_text[:240] or title,
                    "suggested_next_action": f"Review the {app_name or 'Worklog'} thought(s) and convert into a tracked item.",
                    "source_thoughts": source_refs,
                }
            )

    if not proposed_items:
        for item in items:
            raw = item.get("raw_text", "")
            inferred = _infer_thought(raw)
            proposed_items.append(
                {
                    "title": (inferred["ai_inferred_app"] or "Worklog") + " follow-up",
                    "destination_folder": {
                        "bug": "04-inbox/bugs",
                        "feature": "04-inbox/features",
                        "support": "04-inbox/support",
                        "blocker": "04-inbox/new",
                    }.get(inferred["ai_inferred_type"], "04-inbox/new"),
                    "type": inferred["ai_inferred_type"] if inferred["ai_inferred_type"] in {"bug", "feature", "support"} else "note",
                    "app_project": inferred["ai_inferred_app"] or "worklog",
                    "priority": "medium",
                    "plain_english_summary": raw[:240],
                    "suggested_next_action": "Review this thought and decide whether it should become a Worklog item.",
                    "source_thoughts": [item.get("path", "")],
                }
            )

    prompt = "\n".join(
        [
            "You are the FSFT Worklog Assistant.",
            "Use Worklog and KB context only.",
            "Convert the thoughts into concrete Worklog inbox suggestions and a Codex prompt.",
            "Do not move files in preview mode.",
        ]
    )
    return {
        "plain_summary": f"{len(items)} undigested thought item(s) ready for review.",
        "grouped_by_app": {app: len(thoughts) for app, thoughts in grouped.items()},
        "likely_bugs": [item["plain_english_summary"] for item in proposed_items if item["type"] == "bug"][:5],
        "likely_features": [item["plain_english_summary"] for item in proposed_items if item["type"] == "feature"][:5],
        "likely_blockers": [item["plain_english_summary"] for item in proposed_items if item["destination_folder"] == "04-inbox/new" and item["priority"] == "high"][:5],
        "proposed_items": proposed_items,
        "recommended_codex_prompt": prompt,
        "kb_context_excerpt": _kb_reference_text()[:6000],
    }


def _dashboard_documents() -> list[dict[str, object]]:
    docs = []
    for item in TOP_DASHBOARD_FILES:
        source_path = WORKLOG_ROOT / item["path"]
        source_text = source_path.read_text(encoding="utf-8")
        docs.append(
            {
                **item,
                "html": _render_markdown(source_text),
            }
        )
    return docs


def _first_nonempty_paragraph(markdown_text: str) -> str:
    paragraphs = [part.strip() for part in markdown_text.split("\n\n") if part.strip()]
    for paragraph in paragraphs:
        if paragraph.startswith("#"):
            continue
        cleaned = re.sub(r"^[-*]\s*", "", paragraph).strip()
        if cleaned:
            return cleaned
    return ""


def _focus_summary() -> dict[str, str]:
    current_focus = _read_markdown("00-dashboard/current-focus.md")
    engineering = _read_markdown("00-dashboard/engineering-priorities.md")
    next_actions = _read_markdown("00-dashboard/next-actions.md")
    first_priority_line = ""
    for line in engineering.splitlines():
        if line.startswith("| P1 |"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 6:
                first_priority_line = f"{cells[1]}: {cells[2]}"
            break
    return {
        "greeting": "Good to see you, David.",
        "date": datetime.now(timezone.utc).strftime("%A, %B %-d, %Y"),
        "focus": _first_nonempty_paragraph(current_focus) or "Keep the Worklog current and the day easy to resume.",
        "summary": _first_nonempty_paragraph(current_focus) or "The Worklog should make the next decision obvious.",
        "top_priority": first_priority_line or "Keep the current top priority moving first.",
        "today_actions": _extract_section_text(next_actions, "Next Actions"),
    }


def _today_focus_items(limit: int = 3) -> list[dict[str, str]]:
    items = []
    next_actions_text = _extract_section_text(_read_markdown("00-dashboard/next-actions.md"), "Next Actions")
    for line in next_actions_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item:
                items.append({"text": item, "kind": "next action"})
    if len(items) < limit:
        for line in _extract_section_text(_read_markdown("00-dashboard/blockers.md"), "Blockers").splitlines():
            line = line.strip()
            if line.startswith("- "):
                item = line[2:].strip()
                if item:
                    items.append({"text": item, "kind": "blocker"})
    return items[:limit]


def _today_blockers(limit: int = 3) -> list[str]:
    blockers = []
    for line in _extract_section_text(_read_markdown("00-dashboard/blockers.md"), "Blockers").splitlines():
        line = line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item:
                blockers.append(item)
    return blockers[:limit]


def _triage_items(limit: int = 8) -> list[dict[str, str]]:
    items = []
    for item in _all_structured_inbox_items():
        if item.get("category") == "new":
            items.append(item)
    return items[:limit]


def _pretty_title(path: str) -> str:
    mapping = {
        "ims.md": "IMS",
        "dispatch.md": "Dispatch",
        "parking.md": "Parking",
        "unity.md": "Unity",
        "core.md": "Core",
        "cy-storage.md": "CY Storage",
        "worklog.md": "Worklog",
    }
    return mapping.get(Path(path).name, Path(path).stem.replace("-", " ").title())


def _unity_launcher_url(next_path: str | None = None) -> str:
    base_url = app.config["UNITY_BASE_URL"].rstrip("/")
    launcher_url = urljoin(base_url + "/", "launcher")
    if next_path:
        separator = "&" if "?" in launcher_url else "?"
        return f"{launcher_url}{separator}next={quote(next_path, safe='/')}"
    return launcher_url


def _build_assertion_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret_key=app.config["WORKLOG_ASSERTION_SECRET"],
        salt=app.config["WORKLOG_ASSERTION_SALT"],
    )


def _extract_assertion_value() -> str:
    return (
        request.args.get("assertion.value")
        or request.args.get("assertion")
        or ""
    ).strip()


def _safe_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _load_assertion_claims(assertion_value: str) -> dict[str, object] | None:
    serializer = _build_assertion_serializer()
    try:
        claims = serializer.loads(
            assertion_value,
            max_age=app.config["WORKLOG_ASSERTION_MAX_AGE_SECONDS"],
        )
    except SignatureExpired:
        return None
    except BadSignature:
        return None

    return claims if isinstance(claims, dict) else None


def _normalize_claims(claims: dict[str, object]) -> dict[str, object] | None:
    required = [
        "version",
        "token_type",
        "iss",
        "aud",
        "sub",
        "core_user_id",
        "username",
        "active",
        "roles",
        "permissions",
        "application_keys",
        "portal_keys",
        "iat",
        "exp",
        "jti",
    ]
    for field in required:
        if field not in claims:
            return None

    roles = _safe_list(claims.get("roles"))
    permissions = _safe_list(claims.get("permissions"))
    application_keys = _safe_list(claims.get("application_keys"))
    portal_keys = _safe_list(claims.get("portal_keys"))

    if not all(isinstance(value, str) and value.strip() for value in roles):
        return None
    if not all(isinstance(value, str) and value.strip() for value in permissions):
        return None
    if not all(isinstance(value, str) and value.strip() for value in application_keys):
        return None
    if not all(isinstance(value, str) and value.strip() for value in portal_keys):
        return None

    normalized = {
        "version": claims.get("version"),
        "token_type": claims.get("token_type"),
        "iss": claims.get("iss"),
        "aud": claims.get("aud"),
        "sub": claims.get("sub"),
        "core_user_id": str(claims.get("core_user_id") or "").strip(),
        "username": str(claims.get("username") or "").strip(),
        "email": str(claims.get("email") or "").strip(),
        "active": bool(claims.get("active")),
        "roles": roles,
        "permissions": permissions,
        "application_keys": application_keys,
        "portal_keys": portal_keys,
        "iat": claims.get("iat"),
        "exp": claims.get("exp"),
        "jti": claims.get("jti"),
    }

    if normalized["version"] != ASSERTION_VERSION:
        return None
    if normalized["token_type"] != ASSERTION_TYPE:
        return None
    if normalized["iss"] != ASSERTION_ISSUER:
        return None
    if normalized["aud"] != WORKLOG_APPLICATION_KEY:
        return None
    if normalized["sub"] != normalized["core_user_id"]:
        return None
    if not normalized["active"]:
        return None
    if WORKLOG_APPLICATION_KEY not in [key.strip().lower() for key in normalized["application_keys"]]:
        return None
    if "super admin" not in [role.strip().lower() for role in normalized["roles"]]:
        return None

    return normalized


def _set_worklog_session(claims: dict[str, object]) -> None:
    session[WORKLOG_SESSION_KEY] = {
        "core_user_id": claims["core_user_id"],
        "username": claims["username"],
        "email": claims["email"],
        "roles": claims["roles"],
        "permissions": claims["permissions"],
        "application_keys": claims["application_keys"],
        "portal_keys": claims["portal_keys"],
        "authenticated_at": claims["iat"],
        "expires_at": claims["exp"],
    }
    session.modified = True


def _clear_worklog_session() -> None:
    session.pop(WORKLOG_SESSION_KEY, None)
    session.modified = True


def _current_identity():
    identity = session.get(WORKLOG_SESSION_KEY)
    if not isinstance(identity, dict):
        return None
    if not identity.get("core_user_id") or not identity.get("username"):
        _clear_worklog_session()
        return None
    return identity


def _is_authenticated() -> bool:
    return _current_identity() is not None


def _is_super_admin() -> bool:
    identity = _current_identity()
    if identity is None:
        return False
    return "super admin" in {str(role).strip().lower() for role in identity.get("roles", [])}


def _require_worklog_session(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _is_authenticated():
            return redirect(_unity_launcher_url(request.full_path.rstrip("?")))
        if not _is_super_admin():
            abort(403)
        return view(*args, **kwargs)

    return wrapped


@app.context_processor
def inject_globals() -> dict[str, object]:
    return {
        "nav_items": _nav_items(),
        "content_root": str(WORKLOG_ROOT),
        "now_utc": None,
        "is_authenticated": _is_authenticated(),
        "is_super_admin": _is_super_admin(),
    }


@app.route("/")
@_require_worklog_session
def dashboard():
    app_cards = [_parse_active_work_file(item["path"], item["title"]) for item in ACTIVE_WORK_FILES]
    counts = _dashboard_counts()
    inbox_items = _recent_inbox_items()
    update_shipments = _assistant_update_shipments()

    return render_template(
        "dashboard.html",
        counts=counts,
        app_cards=app_cards,
        inbox_items=inbox_items,
        update_shipments=update_shipments,
    )


@app.route("/roadmap")
@_require_worklog_session
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
@_require_worklog_session
def active_work():
    files = [
        "03-active-work/ims.md",
        "03-active-work/dispatch.md",
        "03-active-work/parking.md",
        "03-active-work/unity.md",
        "03-active-work/core.md",
        "03-active-work/cy-storage.md",
        "03-active-work/worklog.md",
    ]
    sections = [{"path": path, "title": _pretty_title(path), "html": _render_markdown(_read_markdown(path))} for path in files]
    return render_template("section.html", title="Active Work", sections=sections)


@app.route("/daily-logs")
@_require_worklog_session
def daily_logs():
    logs = [str(path.relative_to(WORKLOG_ROOT)) for path in sorted((WORKLOG_ROOT / "01-daily-logs").glob("*/*/*.md"), reverse=True)]
    return render_template("listing.html", title="Daily Logs", items=logs)


@app.route("/decisions")
@_require_worklog_session
def decisions():
    return render_template("listing.html", title="Decisions", items=_category_files("04-decisions"))


@app.route("/release-notes")
@_require_worklog_session
def release_notes():
    return render_template("listing.html", title="Release Notes", items=_category_files("05-release-notes"))


@app.route("/ideas")
@_require_worklog_session
def ideas():
    return render_template("listing.html", title="Ideas", items=_category_files("06-ideas"))


@app.route("/runbooks")
@_require_worklog_session
def runbooks():
    return render_template("listing.html", title="Runbooks", items=_category_files("11-runbooks"))


@app.route("/inbox")
@_require_worklog_session
def inbox():
    inbox_type = (request.args.get("type") or "all").strip().lower()
    if inbox_type == "triaged":
        inbox_type = "all"
    if inbox_type not in INBOX_TYPES:
        inbox_type = "all"
    app_slug = _normalize_app_filter(request.args.get("app"))
    items = _filter_inbox_queue_items(_inbox_queue_items(), inbox_type, app_slug)
    filters = {
        "type": inbox_type,
        "app": app_slug,
    }
    return render_template(
        "inbox.html",
        title="Inbox",
        items=items,
        inbox_type=inbox_type,
        app_filter=app_slug,
        filters=filters,
        inbox_types=[
            {"value": "all", "label": "All"},
            {"value": "new", "label": "New"},
            {"value": "bugs", "label": "Bugs"},
            {"value": "features", "label": "Features"},
            {"value": "support", "label": "Support"},
            {"value": "closed", "label": "Closed"},
        ],
        app_filters=[
            {"value": "all", "label": "All Apps"},
            {"value": "core", "label": "Core"},
            {"value": "unity", "label": "Unity"},
            {"value": "ims", "label": "IMS"},
            {"value": "cy-storage", "label": "CY Storage"},
            {"value": "dispatch", "label": "Dispatch"},
            {"value": "parking", "label": "Parking"},
            {"value": "hiring", "label": "Hiring"},
            {"value": "worklog", "label": "Worklog"},
            {"value": "other", "label": "Other"},
        ],
    )


@app.route("/inbox/new")
@_require_worklog_session
def inbox_new():
    return redirect(url_for("inbox", type="new"))


@app.route("/inbox/bugs")
@_require_worklog_session
def inbox_bugs():
    return redirect(url_for("inbox", type="bugs"))


@app.route("/inbox/features")
@_require_worklog_session
def inbox_features():
    return redirect(url_for("inbox", type="features"))


@app.route("/inbox/support")
@_require_worklog_session
def inbox_support():
    return redirect(url_for("inbox", type="support"))


@app.route("/inbox/closed")
@_require_worklog_session
def inbox_closed():
    return redirect(url_for("inbox", type="closed"))


@app.route("/intake", methods=["GET", "POST"])
@_require_worklog_session
def intake():
    if request.method == "POST":
        created_path = _create_inbox_item_from_form(request.form)
        return redirect(url_for("view_file", relative_path=str(created_path.relative_to(WORKLOG_ROOT))))

    intake_counts = _dashboard_intake_counts()
    intake_items = _all_structured_inbox_items()[:8]
    plain_mode = _intake_plain_mode_enabled()
    return render_template(
        "intake.html",
        intake_counts=intake_counts,
        intake_items=intake_items,
        plain_mode=plain_mode,
    )


@app.route("/assistant")
@_require_worklog_session
def assistant():
    conversation = _thought_box_items(digested_only=False)[:12]
    digest_preview = None
    if request.args.get("digest_preview") == "1":
        digest_preview = _digest_groups_from_items(_thought_box_items(digested_only=False))
    return render_template(
        "assistant.html",
        conversation=conversation,
        digest_preview=digest_preview,
        update_shipments=_assistant_update_shipments(),
        openai_enabled=_openai_available(),
        idea_inventory_count=len(_thought_box_items(digested_only=False)),
    )


@app.route("/api/assistant/thoughts")
@_require_worklog_session
def assistant_thoughts():
    return {"thoughts": _thought_box_items(digested_only=False)}


@app.route("/api/assistant/message", methods=["POST"])
@_require_worklog_session
def assistant_message():
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return {"error": "message is required"}, 400
    if message.lower() in {"digest my thought box", "digest idea inventory", "digest idea orders"}:
        preview = _digest_groups_from_items(_thought_box_items(digested_only=False))
        return {
            "ok": True,
            "assistant_reply": "Proposed update review prepared. Review the proposal before approving.",
            "digest_preview": preview,
            "created_raw_thought": False,
        }
    thought_path = _write_thought_file(message)
    inferred = _infer_thought(message)
    data = {
        "ok": True,
        "thought_path": str(thought_path.relative_to(WORKLOG_ROOT)),
        "assistant_reply": "Saved your idea. I can digest it when you ask.",
        "digest_status": "not_digested",
        **inferred,
    }
    if _openai_available():
        data["assistant_reply"] = "I saved that idea. OpenAI-backed digestion is available, but the assistant stays scoped to Worklog and KB context."
    else:
        data["assistant_reply"] = _safe_openai_error()
    return data


@app.route("/api/assistant/digest-preview", methods=["POST"])
@_require_worklog_session
def assistant_digest_preview():
    payload = request.get_json(silent=True) or {}
    thought_paths = payload.get("thought_paths") or []
    if thought_paths:
        thoughts = _thoughts_by_paths([str(path) for path in thought_paths])
    else:
        thoughts = _thought_box_items(digested_only=False)
    preview = _digest_groups_from_items(thoughts)
    return {"ok": True, "digest_preview": preview, "thought_count": len(thoughts)}


@app.route("/api/assistant/approve-digest", methods=["POST"])
@_require_worklog_session
def assistant_approve_digest():
    payload = request.get_json(silent=True) or {}
    preview = payload.get("digest_preview") or {}
    source_paths = [str(path) for path in preview.get("source_thoughts", [])]
    thoughts = _thoughts_by_paths(source_paths)
    if not thoughts:
        return {"ok": False, "error": "No active thoughts available for approval."}, 400

    by_path = {item["path"]: item for item in thoughts}
    created_items: list[str] = []
    moved_paths: list[str] = []
    for proposal in preview.get("proposed_items", []):
        proposal_paths = [str(path) for path in proposal.get("source_thoughts", [])]
        active_thoughts = [by_path[path] for path in proposal_paths if path in by_path]
        if not active_thoughts:
            continue
        fingerprints = {_thought_item_fingerprint(item) for item in active_thoughts}
        if len(fingerprints) == 0:
            continue
        if proposal.get("destination_folder") == "04-inbox/thought-box/digested":
            continue
        worklog_path = _create_worklog_item_from_proposal(proposal)
        created_items.append(str(worklog_path.relative_to(WORKLOG_ROOT)))
        for thought in active_thoughts:
            source_file = WORKLOG_ROOT / thought["path"]
            if not source_file.exists():
                continue
            destination = _move_thought(source_file, _thought_digested_dir())
            moved_paths.append(str(destination.relative_to(WORKLOG_ROOT)))

    record_path = THOUGHT_BOX_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-digest-record.md"
    created_lines = [f"- {item}" for item in created_items] or ["- None"]
    moved_lines = [f"- {item}" for item in moved_paths] or ["- None"]
    record_path.write_text(
        "\n".join(
            [
                "# Assistant Digest Record",
                "",
                f"- created_at: {datetime.now(timezone.utc).isoformat()}",
                f"- source_count: {len(thoughts)}",
                f"- created_items: {len(created_items)}",
                "",
                "## Created Worklog Items",
                *created_lines,
                "",
                "## Moved Thought Files",
                *moved_lines,
                "",
            ]
        ),
        encoding="utf-8",
    )

    update_record = _write_update_shipment_record(preview, created_items, moved_paths)

    return {
        "ok": True,
        "created_items": created_items,
        "moved_thoughts": moved_paths,
        "update_shipment": str(update_record.relative_to(WORKLOG_ROOT)),
        "assistant_reply": "Update approved. Routed items were created and raw ideas were moved to digested.",
    }


@app.route("/api/assistant/archive-thought", methods=["POST"])
@_require_worklog_session
def assistant_archive_thought():
    payload = request.get_json(silent=True) or {}
    thought_path = str(payload.get("thought_path") or "").strip()
    if not thought_path:
        return {"ok": False, "error": "thought_path is required"}, 400
    source = WORKLOG_ROOT / thought_path
    if not source.exists():
        return {"ok": False, "error": "thought not found"}, 404
    destination = _move_thought(source, _thought_archived_dir())
    return {"ok": True, "archived_path": str(destination.relative_to(WORKLOG_ROOT))}


@app.route("/view/<path:relative_path>")
@_require_worklog_session
def view_file(relative_path: str):
    source = _read_markdown(relative_path)
    return render_template(
        "document.html",
        title=Path(relative_path).name,
        relative_path=relative_path,
        html=_render_markdown(source),
    )


@app.route("/sso/launch", methods=["GET"])
@app.route("/sso/callback", methods=["GET"])
def sso_launch():
    assertion_value = _extract_assertion_value()
    if not assertion_value:
        return redirect(_unity_launcher_url())

    claims = _load_assertion_claims(assertion_value)
    if claims is None:
        return render_template("access_denied.html", reason="Your Worklog launch assertion could not be validated."), 403

    normalized_claims = _normalize_claims(claims)
    if normalized_claims is None:
        return render_template("access_denied.html", reason="You do not have permission to access Worklog."), 403

    _set_worklog_session(normalized_claims)
    return redirect(url_for("dashboard"))


@app.route("/logout", methods=["POST"])
@_require_worklog_session
def logout():
    _clear_worklog_session()
    return redirect(_unity_launcher_url())


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/category/<path:category>")
@_require_worklog_session
def category_view(category: str):
    files = _category_files(category)
    if not files:
        abort(404)
    return render_template("listing.html", title=category.replace("-", " ").title(), items=files)


@app.errorhandler(403)
def forbidden(_):
    return render_template("access_denied.html", reason="You do not have permission to access Worklog."), 403


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5075, debug=False)
