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
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
import markdown
import validation_session_lib as validation_session_store


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
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")
THOUGHT_BOX_DIR = WORKLOG_ROOT / "04-inbox/thought-box"
SPRINT_HANDOFFS_DIR = WORKLOG_ROOT / "05-sprint-handoffs"
SPRINTS_ROOT_DIR = WORKLOG_ROOT / "06-sprints"
USER_NOTIFICATIONS_DIR = WORKLOG_ROOT / "04-inbox/notifications"
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
APP_ORDER = ["Core", "Unity", "IMS", "CY Storage", "Dispatch", "Parking", "Hiring", "Worklog", "Other"]
SPRINT_CODE_PREFIXES = {
    "core": "CORE",
    "unity": "UNITY",
    "ims": "IMS",
    "cy-storage": "CY",
    "dispatch": "DISPATCH",
    "parking": "PARKING",
    "hiring": "HIRING",
    "worklog": "WL",
    "other": "OTHER",
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
                {"label": "Sprint Queue", "endpoint": "sprints"},
                {"label": "Updates", "endpoint": "release_notes"},
                {"label": "Inbox", "endpoint": "inbox"},
                {"label": "Daily Log", "endpoint": "daily_logs"},
            ],
        },
        {
            "label": "More",
            "items": [
                {"label": "Validation Sessions", "endpoint": "validation_sessions"},
                {"label": "User Requests", "endpoint": "intake"},
                {"label": "Portfolio Status", "endpoint": "view_file", "args": {"relative_path": "00-dashboard/portfolio-status.md"}},
                {"label": "Engineering Priorities", "endpoint": "view_file", "args": {"relative_path": "00-dashboard/engineering-priorities.md"}},
                {"label": "Roadmap", "endpoint": "roadmap"},
                {"label": "Active Work", "endpoint": "active_work"},
                {"label": "Runbooks", "endpoint": "runbooks"},
                {"label": "Decisions", "endpoint": "decisions"},
                {"label": "Release Notes", "endpoint": "release_notes"},
                {"label": "Notifications", "endpoint": "notifications_preview"},
                {"label": "Ideas", "endpoint": "ideas"},
                {"label": "Inbox", "endpoint": "inbox"},
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


def _ensure_user_requests_dir() -> None:
    _user_requests_dir().mkdir(parents=True, exist_ok=True)


def _ensure_user_notifications_dir() -> None:
    _user_notifications_dir().mkdir(parents=True, exist_ok=True)


def _user_requests_dir() -> Path:
    return WORKLOG_ROOT / "04-inbox/requests"


def _user_notifications_dir() -> Path:
    return WORKLOG_ROOT / "04-inbox/notifications"


def _request_source_type_label(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    mapping = {
        "customer": "Customer",
        "employee": "Employee",
        "vendor": "Vendor",
        "internal": "Internal",
        "unknown": "Unknown",
    }
    return mapping.get(normalized, "Unknown")


def _parse_user_request_item(path: Path) -> dict[str, str]:
    data = _parse_structured_inbox_item(path)
    text = path.read_text(encoding="utf-8")
    current_section = None
    for line in text.splitlines():
        if line.startswith("- ") and ":" in line[2:]:
            key, value = line[2:].split(":", 1)
            data[key.strip().lower().replace(" ", "_")] = value.strip()
        elif line.startswith("## "):
            current_section = line[3:].strip().lower().replace(" ", "_")
            data.setdefault(current_section, "")
        elif current_section and line.strip():
            data[current_section] = (data.get(current_section, "") + "\n" + line).strip()
    data["request_title"] = data.get("request_title") or data.get("title") or path.stem.replace("-", " ").title()
    data["request_details"] = data.get("request_details") or data.get("plain_english_summary") or data.get("technical_notes") or data["request_title"]
    data["requester_name"] = data.get("requester_name") or data.get("requested_by") or "Unknown"
    data["requester_email"] = data.get("requester_email") or ""
    data["organization"] = data.get("organization") or ""
    data["source_type"] = _request_source_type_label(data.get("source_type"))
    data["request_status"] = (data.get("request_status") or data.get("status") or "New").title()
    data["app_project"] = data.get("app_project") or data.get("app") or "Worklog"
    data["created_at"] = data.get("created_at") or data.get("created_date") or ""
    data["updated_at"] = data.get("updated_at") or ""
    data["request_id"] = data.get("request_id") or data.get("id") or str(path.relative_to(WORKLOG_ROOT))
    data["idea_path"] = data.get("idea_path") or ""
    data["mtime"] = _file_mtime(path)
    data["mtime_display"] = _format_file_timestamp(path)
    data["path"] = str(path.relative_to(WORKLOG_ROOT))
    return data


def _user_requests_items() -> list[dict[str, str]]:
    _ensure_user_requests_dir()
    items = [_parse_user_request_item(path) for path in sorted(_user_requests_dir().glob("*.md")) if path.is_file()]
    items.sort(key=lambda item: (item.get("mtime", 0), item["path"]), reverse=True)
    return items


def _request_record_by_id(request_id: str) -> dict[str, str] | None:
    request_id = (request_id or "").strip()
    for item in _user_requests_items():
        if request_id in {item.get("request_id"), item.get("path"), Path(item.get("path") or "").name}:
            return item
    return None


def _notifications_for_request(request_id: str) -> list[dict[str, str]]:
    request_id = (request_id or "").strip()
    if not request_id:
        return []
    return [item for item in _notification_items() if item.get("request_id") == request_id or item.get("request_id") == request_id or item.get("request_title") == request_id]


def _parse_notification_item(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    data = _parse_key_value_metadata(text)
    data["path"] = str(path.relative_to(WORKLOG_ROOT))
    data["title"] = data.get("title") or path.stem.replace("-", " ").title()
    data["request_id"] = data.get("request_id") or ""
    data["email"] = data.get("email") or ""
    data["notification_type"] = data.get("notification_type") or ""
    data["status"] = (data.get("status") or "pending").lower()
    data["sent_at"] = data.get("sent_at") or ""
    data["error_message"] = data.get("error_message") or ""
    data["subject"] = data.get("subject") or ""
    data["body"] = data.get("body") or _extract_section_text(text, "Body")
    data["generated_at"] = data.get("generated_at") or data.get("created_at") or _format_file_timestamp(path)
    data["request_title"] = data.get("request_title") or ""
    data["idea_path"] = data.get("idea_path") or ""
    data["sprint_code"] = data.get("sprint_code") or ""
    data["sprint_path"] = data.get("sprint_path") or ""
    data["mtime"] = _file_mtime(path)
    data["mtime_display"] = _format_file_timestamp(path)
    return data


def _notification_items() -> list[dict[str, str]]:
    _ensure_user_notifications_dir()
    items = [_parse_notification_item(path) for path in sorted(_user_notifications_dir().glob("*.md")) if path.is_file()]
    items.sort(key=lambda item: (item.get("mtime", 0), item["path"]), reverse=True)
    return items


def _create_request_live_notifications_for_sprint(record: dict[str, object]) -> list[Path]:
    created: list[Path] = []
    request_ids = list(dict.fromkeys([
        *[str(item).strip() for item in record.get("source_request_ids", []) if str(item).strip()],
        *[str(item).strip() for item in record.get("source_request_paths", []) if str(item).strip()],
    ]))
    if not request_ids:
        source_thoughts = _resolve_sprint_source_thoughts(record)
        for thought in source_thoughts:
            request_path = str(thought.get("source_request_path") or "").strip()
            request_id = str(thought.get("source_request_id") or request_path or "").strip()
            if request_id:
                request_ids.append(request_id)
    for request_id in dict.fromkeys(request_ids):
        request_record = _request_record_by_id(request_id)
        if not request_record:
            continue
        created.append(
            _create_notification_event(
                request_id=request_record["request_id"],
                email=request_record.get("requester_email") or "",
                notification_type="request_live",
                status="generated",
                subject="Your request is now live",
                body="\n".join(
                    [
                        "Your request has been implemented and deployed to production.",
                        "",
                        "Request:",
                        request_record.get("request_title") or request_record.get("title") or "User Request",
                        "",
                        "What changed:",
                        str(record.get("plain_english_release_notes") or "Not recorded yet"),
                        "",
                        "Thank you for helping improve the platform.",
                    ]
                ),
                request_title=request_record.get("request_title") or request_record.get("title") or "",
                sprint_code=str(record.get("sprint_code") or record.get("intended_sprint_code") or ""),
                sprint_path=str(record.get("path") or ""),
            )
        )
    if not created:
        source_titles = {str(item).strip().lower() for item in record.get("source_idea_summaries", []) if str(item).strip()}
        if not source_titles:
            source_titles = {str(item).strip().lower() for item in record.get("canonical_source_ideas", []) if str(item).strip()}
        source_thought_paths = {str(item).strip() for item in record.get("source_thought_paths", []) if str(item).strip()}
        if source_titles:
            for request_record in _user_requests_items():
                haystack = " ".join(
                    [
                        str(request_record.get("request_title") or ""),
                        str(request_record.get("request_details") or ""),
                    ]
                ).lower()
                request_idea_path = str(request_record.get("idea_path") or "").strip()
                path_matches = request_idea_path and request_idea_path in source_thought_paths
                if not path_matches and not any(title and title in haystack for title in source_titles):
                    continue
                created.append(
                    _create_notification_event(
                        request_id=request_record["request_id"],
                        email=request_record.get("requester_email") or "",
                        notification_type="request_live",
                        status="generated",
                        subject="Your request is now live",
                        body="\n".join(
                            [
                                "Your request has been implemented and deployed to production.",
                                "",
                                "Request:",
                                request_record.get("request_title") or request_record.get("title") or "User Request",
                                "",
                                "What changed:",
                                str(record.get("plain_english_release_notes") or "Not recorded yet"),
                                "",
                                "Thank you for helping improve the platform.",
                            ]
                        ),
                        request_title=request_record.get("request_title") or request_record.get("title") or "",
                        sprint_code=str(record.get("sprint_code") or record.get("intended_sprint_code") or ""),
                        sprint_path=str(record.get("path") or ""),
                    )
                )
                break
    if not created:
        converted_requests = [item for item in _user_requests_items() if str(item.get("request_status") or "").lower() == "converted" and str(item.get("idea_path") or "").strip()]
        if len(converted_requests) == 1:
            request_record = converted_requests[0]
            created.append(
                _create_notification_event(
                    request_id=request_record["request_id"],
                    email=request_record.get("requester_email") or "",
                    notification_type="request_live",
                    status="generated",
                    subject="Your request is now live",
                    body="\n".join(
                        [
                            "Your request has been implemented and deployed to production.",
                            "",
                            "Request:",
                            request_record.get("request_title") or request_record.get("title") or "User Request",
                            "",
                            "What changed:",
                            str(record.get("plain_english_release_notes") or "Not recorded yet"),
                            "",
                            "Thank you for helping improve the platform.",
                        ]
                    ),
                    request_title=request_record.get("request_title") or request_record.get("title") or "",
                    sprint_code=str(record.get("sprint_code") or record.get("intended_sprint_code") or ""),
                    sprint_path=str(record.get("path") or ""),
                )
            )
    return created


def _create_notification_event(
    *,
    request_id: str,
    email: str = "",
    notification_type: str,
    status: str = "pending",
    subject: str,
    body: str,
    request_title: str = "",
    idea_path: str = "",
    sprint_code: str = "",
    sprint_path: str = "",
    error_message: str = "",
) -> Path:
    _ensure_user_notifications_dir()
    generated_at = datetime.now(timezone.utc).isoformat()
    filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{_slugify_title(notification_type)}-{_slugify_title(request_title or request_id)}.md"
    target = _user_notifications_dir() / filename
    if target.exists():
        target = _user_notifications_dir() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{_slugify_title(notification_type)}-{_slugify_title(request_title or request_id)}-1.md"
    target.write_text(
        "\n".join(
            [
                f"# Notification: {notification_type}",
                "",
                f"- request_id: {request_id}",
                f"- request_title: {request_title}",
                f"- email: {email}",
                f"- notification_type: {notification_type}",
                f"- status: {status}",
                f"- sent_at: {''}",
                f"- generated_at: {generated_at}",
                f"- error_message: {error_message}",
                f"- subject: {subject}",
                f"- idea_path: {idea_path}",
                f"- sprint_code: {sprint_code}",
                f"- sprint_path: {sprint_path}",
                "",
                "## Body",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return target


def _slugify_request_title(value: str) -> str:
    return _slugify_title(value)


def _create_user_request_from_form(form: dict[str, str]) -> Path:
    _ensure_user_requests_dir()
    title = (form.get("request_title") or form.get("title") or "").strip() or "Untitled Request"
    details = (form.get("request_details") or form.get("details") or "").strip()
    requester_name = (form.get("requester_name") or form.get("requested_by") or "").strip() or "Unknown"
    requester_email = (form.get("requester_email") or "").strip()
    organization = (form.get("organization") or "").strip()
    source_type = _request_source_type_label(form.get("source_type"))
    app_project = (form.get("app_project") or form.get("app") or "").strip() or "worklog"
    created_at = datetime.now(timezone.utc).isoformat()
    filename = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{_slugify_request_title(title)}.md"
    target = _user_requests_dir() / filename
    if target.exists():
        target = _user_requests_dir() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{_slugify_request_title(title)}.md"
    request_id = str(target.relative_to(WORKLOG_ROOT))
    content = "\n".join(
        [
            f"# {title}",
            "",
            f"- request_id: {request_id}",
            f"- request_title: {title}",
            f"- request_details: {details}",
            f"- requester_name: {requester_name}",
            f"- requester_email: {requester_email}",
            f"- organization: {organization}",
            f"- source_type: {source_type}",
            f"- request_status: New",
            f"- app_project: {app_project}",
            f"- created_at: {created_at}",
            f"- updated_at: {created_at}",
            "",
            "## Request Details",
            details or "TBD",
            "",
        ]
    )
    target.write_text(content, encoding="utf-8")
    _create_notification_event(
        request_id=request_id,
        email=requester_email,
        notification_type="request_received",
        status="pending",
        subject="We've received your request",
        body="\n".join(
            [
                "Thank you for your request.",
                "",
                "We have received and recorded your request and added it to our review queue.",
                "",
                "Request:",
                title,
                "",
                "Reference:",
                request_id,
                "",
                "We will notify you again if the request enters our development workflow.",
            ]
        ),
        request_title=title,
    )
    return target


def _update_user_request_file(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for key, value in updates.items():
        pattern = rf"^- {re.escape(key)}: .*?$"
        replacement = f"- {key}: {value}"
        if re.search(pattern, text, flags=re.M):
            text = re.sub(pattern, replacement, text, flags=re.M)
        else:
            insert_at = text.find("\n\n")
            if insert_at == -1:
                text += f"\n{replacement}"
            else:
                text = text[: insert_at + 2] + f"{replacement}\n" + text[insert_at + 2 :]
    text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {datetime.now(timezone.utc).isoformat()}", text, flags=re.M)
    path.write_text(text, encoding="utf-8")


def _convert_user_request_to_idea(path: Path) -> Path:
    request = _parse_user_request_item(path)
    message_parts = [
        request.get("request_title") or request.get("title") or "User Request",
        request.get("request_details") or "",
        f"Requester: {request.get('requester_name') or 'Unknown'}",
        f"Email: {request.get('requester_email') or ''}",
        f"Organization: {request.get('organization') or ''}",
        f"Source Type: {request.get('source_type') or 'Unknown'}",
    ]
    thought_path = _write_thought_file("\n".join(part for part in message_parts if part).strip())
    _update_thought_file(
        thought_path,
        {
            "source_request_path": str(path.relative_to(WORKLOG_ROOT)),
            "source_request_id": str(path.relative_to(WORKLOG_ROOT)),
            "source_request_title": request.get("request_title") or request.get("title") or "",
            "status": "raw",
            "digest_status": "not_digested",
        },
    )
    _update_user_request_file(path, {"request_status": "Converted", "idea_path": str(thought_path.relative_to(WORKLOG_ROOT))})
    _create_notification_event(
        request_id=str(path.relative_to(WORKLOG_ROOT)),
        email=request.get("requester_email") or "",
        notification_type="entered_development",
        status="pending",
        subject="Your request has entered development",
        body="\n".join(
            [
                "Your request has been reviewed and entered our development workflow.",
                "",
                "Request:",
                request.get("request_title") or request.get("title") or "User Request",
                "",
                "We will notify you again if this request is released into production.",
            ]
        ),
        request_title=request.get("request_title") or request.get("title") or "",
        idea_path=str(thought_path.relative_to(WORKLOG_ROOT)),
    )
    return thought_path


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _format_file_timestamp(path: Path) -> str:
    try:
        return _format_pacific_timestamp(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
    except OSError:
        return "Unknown"


def _format_local_timestamp(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return _format_pacific_timestamp(dt)


def _format_pacific_date_short(value: datetime | None) -> str:
    if value is None:
        return "Unknown"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(PACIFIC_TZ).strftime("%m/%d/%y")


def _clean_thought_title(value: str) -> str:
    cleaned = str(value or "").strip()
    cleaned = re.sub(r"^\d{4}[- ]\d{2}[- ]\d{2}(?:[- ]\d{2}[- ]\d{2}(?:[- ]\d{2})?)?[- ]*", "", cleaned)
    cleaned = cleaned.replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or "Untitled Thought"


def _format_pacific_timestamp(value: datetime | str | None) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "Unknown"
        normalized = text.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError:
            return text
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local_dt = value.astimezone(PACIFIC_TZ)
    return local_dt.strftime("%Y-%m-%d %I:%M %p %Z").replace(" 0", " ")


app.jinja_env.filters["display_timestamp"] = _format_pacific_timestamp


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


def _app_slug_from_title(title: str) -> str:
    slug = _normalize_app_filter(title)
    return slug if slug != "all" else "other"


def _parse_active_work_file(relative_path: str, title: str) -> dict[str, object]:
    source_path = WORKLOG_ROOT / relative_path
    if not source_path.exists():
        return {
            "title": title,
            "slug": _app_slug_from_title(title),
            "path": relative_path,
            "current_sprint_name": "",
            "current_sprint_status": "Stable",
            "current_sprint_percent": "",
            "current_sprint_notes": "",
            "has_active_sprint": False,
            "last_sprint_name": "",
            "last_sprint_completed": "Not recorded",
            "last_sprint_outcome": "No completion note recorded.",
            "next_suggested_sprint_name": "",
            "next_suggested_sprint_why": "",
            "next_suggested_sprint_first_step": "",
            "blockers_text": "",
            "blockers_count": 0,
            "last_updated": "Unknown",
            "inbox_items": [],
        }
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
        "slug": _app_slug_from_title(title),
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
        "sprint_counts": _sprint_counts_by_app().get(title, {"proposed": 0, "approved": 0, "active": 0, "completed": 0, "shipped": 0}),
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


def _recent_worklog_pages(limit: int = 5) -> list[dict[str, object]]:
    candidate_dirs = [
        WORKLOG_ROOT / "00-dashboard",
        WORKLOG_ROOT / "01-daily-logs",
        WORKLOG_ROOT / "03-active-work",
        WORKLOG_ROOT / "05-release-notes",
        WORKLOG_ROOT / "11-runbooks",
    ]
    items: list[dict[str, object]] = []
    for directory in candidate_dirs:
        if not directory.exists():
            continue
        for path in directory.rglob("*.md"):
            if any(part in {"archived", "digested", "proposed", "rescinded", "deleted"} for part in path.parts):
                continue
            items.append(
                {
                    "title": path.stem.replace("-", " ").title(),
                    "path": str(path.relative_to(WORKLOG_ROOT)),
                    "mtime": _file_mtime(path),
                }
            )
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


def _thought_proposed_dir() -> Path:
    return THOUGHT_BOX_DIR / "proposed"


def _thought_archived_dir() -> Path:
    return THOUGHT_BOX_DIR / "archived"


def _assistant_update_shipments_dir() -> Path:
    return WORKLOG_ROOT / "05-release-notes/assistant-update-shipments"


def _sprint_handoffs_dir() -> Path:
    return SPRINT_HANDOFFS_DIR


def _sprints_dir(status: str | None = None) -> Path:
    root = WORKLOG_ROOT / "06-sprints"
    if status:
        return root / status.lower()
    return root


def _ensure_sprint_dirs() -> None:
    for status in ["proposed", "rejected", "rescinded", "deleted", "approved", "active", "completed", "staged", "shipped", "done", "reconciled"]:
        _sprints_dir(status).mkdir(parents=True, exist_ok=True)


def _ensure_handoff_dirs() -> None:
    for status in ["rescinded", "deleted"]:
        (_sprint_handoffs_dir() / status).mkdir(parents=True, exist_ok=True)


def _proposal_record_path(proposal_id: str, title: str) -> Path:
    return _sprints_dir("proposed") / f"{proposal_id}-{_slugify_title(title)}.md"


def _proposal_id_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _generate_proposal_id() -> str:
    existing = {record.get("proposal_id") for record in _proposed_sprint_records()}
    for sequence in range(1, 1000):
        proposal_id = f"pr-{_proposal_id_prefix()}-{sequence:03d}"
        if proposal_id not in existing:
            return proposal_id
    raise ValueError("Unable to generate a unique proposal id.")


def _write_proposed_sprint_record(group: dict[str, object]) -> Path:
    _ensure_sprint_dirs()
    proposal_id = str(group.get("proposal_id") or _generate_proposal_id())
    title = str(group.get("sprint_group_name") or "Proposed Sprint Group")
    path = _proposal_record_path(proposal_id, title)
    intended_sprint_code = str(group.get("intended_sprint_code") or group.get("sprint_code") or _generate_sprint_code(str(group.get("app_product") or "Other")))
    source_idea_summaries = [str(item) for item in group.get("source_idea_summaries", []) if str(item).strip()]
    source_thoughts = [str(item) for item in group.get("source_thoughts", []) if str(item).strip()]
    if not source_idea_summaries:
        source_idea_summaries = list(dict.fromkeys(source_thoughts))
    proposed_work = [str(item) for item in group.get("proposed_work", []) if str(item).strip()]
    if not proposed_work:
        proposed_work = list(dict.fromkeys(source_idea_summaries or source_thoughts))
    proposed_source_thoughts = [str(item) for item in group.get("proposed_source_thoughts", []) if str(item).strip()]
    handoff_md = _build_handoff_markdown_from_record({**group, "intended_sprint_code": intended_sprint_code}, group.get("thoughts") or [])
    handoff_md = "```markdown\n" + handoff_md + "\n```"
    text = "\n".join(
        [
            f"# Proposed Sprint Group: {title}",
            "",
            f"- proposal_id: {proposal_id}",
            f"- intended_sprint_code: {intended_sprint_code}",
            f"- sprint_group_name: {title}",
            f"- app_product: {group.get('app_product') or 'Other'}",
            f"- scope: {group.get('scope') or 'Small'}",
            f"- status: proposed",
            f"- created_at: {group.get('created_at') or datetime.now(timezone.utc).isoformat()}",
            f"- updated_at: {datetime.now(timezone.utc).isoformat()}",
            f"- purpose: {group.get('purpose') or ''}",
            f"- starting_prompt: {group.get('starting_prompt') or ''}",
            f"- source_thought_ids: {', '.join(str(item) for item in group.get('source_thought_ids', []))}",
            f"- source_thought_paths: {', '.join(str(item) for item in group.get('source_thought_paths', []))}",
            f"- proposed_source_thoughts: {', '.join(proposed_source_thoughts)}",
            f"- source_request_paths: {', '.join(str(item) for item in group.get('source_request_paths', []))}",
            f"- source_request_ids: {', '.join(str(item) for item in group.get('source_request_ids', []))}",
            "",
            "## Source Ideas",
            *([f"- {item}" for item in source_idea_summaries] or [f"- {item}" for item in source_thoughts] or ["- None"]),
            "",
            "## Proposed Source Thoughts",
            *([f"- {item}" for item in proposed_source_thoughts] or ["- None"]),
            "",
            "## Proposed Work",
            *([f"- {item}" for item in proposed_work] or [f"- {item}" for item in source_idea_summaries] or [f"- {item}" for item in source_thoughts] or ["- Triage raw ideas into a focused sprint slice."]),
            "",
            "## Recommended First Step",
            f"{group.get('recommended_first_step') or ''}",
            "",
            "## Handoff Preview",
            handoff_md or "No handoff content found. Regenerate handoff.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")
    return path


def _restore_source_thought_path(source_path: str) -> tuple[str | None, str | None]:
    source_path = source_path.strip()
    if not source_path:
        return None, "missing source path"
    source_file = WORKLOG_ROOT / source_path
    if source_file.name:
        candidate_name = source_file.name
    else:
        candidate_name = Path(source_path).name
    active_target = THOUGHT_BOX_DIR / candidate_name
    holding_candidates = [
        _thought_proposed_dir() / candidate_name,
        _thought_digested_dir() / candidate_name,
    ]
    if source_file.exists():
        if source_file.parent == THOUGHT_BOX_DIR:
            return str(source_file.relative_to(WORKLOG_ROOT)), None
        target = active_target
        if target.exists():
            stem = target.stem
            suffix = target.suffix
            for index in range(2, 1000):
                candidate = THOUGHT_BOX_DIR / f"{stem}-restored-{index:03d}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source_file), str(target))
        except OSError:
            try:
                target.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
            except OSError as exc:
                if target.exists():
                    return str(target.relative_to(WORKLOG_ROOT)), None
                return None, f"unable to restore source idea: {source_path} ({exc})"
        return str(target.relative_to(WORKLOG_ROOT)), None
    for holding_file in holding_candidates:
        if holding_file.exists():
            target = active_target
            if target.exists():
                stem = target.stem
                suffix = target.suffix
                for index in range(2, 1000):
                    candidate = THOUGHT_BOX_DIR / f"{stem}-restored-{index:03d}{suffix}"
                    if not candidate.exists():
                        target = candidate
                        break
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(holding_file), str(target))
            except OSError:
                try:
                    target.write_text(holding_file.read_text(encoding="utf-8"), encoding="utf-8")
                except OSError as exc:
                    if target.exists():
                        return str(target.relative_to(WORKLOG_ROOT)), None
                    return None, f"unable to restore source idea: {source_path} ({exc})"
            return str(target.relative_to(WORKLOG_ROOT)), None
    if active_target.exists():
        return str(active_target.relative_to(WORKLOG_ROOT)), None
    return None, f"missing source idea: {source_path}"


def _recreate_restored_thought(source_path: str, summary: str, sprint_code: str, restore_reason: str, created_at: str = "") -> tuple[str | None, str | None]:
    summary = summary.strip()
    if not summary:
        return None, f"missing source idea: {source_path}"
    source_name = Path(source_path).name or _slugify_title(summary)
    if not source_name.lower().endswith(".md"):
        source_name = f"{Path(source_name).stem}.md"
    target = THOUGHT_BOX_DIR / source_name
    if target.exists():
        stem = target.stem
        suffix = target.suffix or ".md"
        for index in range(2, 1000):
            candidate = THOUGHT_BOX_DIR / f"{stem}-restored-{index:03d}{suffix}"
            if not candidate.exists():
                target = candidate
                break
    target.parent.mkdir(parents=True, exist_ok=True)
    restored_at = datetime.now(timezone.utc).isoformat()
    created_at_value = created_at.strip() or restored_at
    try:
        target.write_text(
            "\n".join(
                [
                    f"# Restored Idea: {source_name}",
                    "",
                    f"- created_at: {created_at_value}",
                    f"- restored_from_sprint_code: {sprint_code or ''}",
                    f"- restored_at: {restored_at}",
                    f"- restore_reason: {restore_reason}",
                    f"- status: raw",
                    f"- digest_status: not_digested",
                    f"- raw_text: {summary}",
                    f"- ai_summary: {summary}",
                    "",
                    "## Raw Thought",
                    summary,
                    "",
                ]
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        if target.exists():
            return str(target.relative_to(WORKLOG_ROOT)), None
        return None, f"unable to recreate source idea: {source_path} ({exc})"
    return str(target.relative_to(WORKLOG_ROOT)), None


def _normalize_restored_thought_file(path: Path, sprint_code: str, restore_reason: str, source_summary: str = "") -> None:
    if not path.exists():
        return
    if path.suffix.lower() != ".md":
        return
    parsed = _parse_thought_file(path)
    raw_text = str(parsed.get("raw_text_full") or source_summary or parsed.get("normalized_summary") or parsed.get("display_snippet") or parsed.get("title") or "").strip()
    if not raw_text:
        return
    created_at = str(parsed.get("created_at") or datetime.now(timezone.utc).isoformat())
    title = str(parsed.get("title") or path.stem.replace("-", " ").title())
    ai_summary = str(parsed.get("ai_summary") or parsed.get("normalized_summary") or raw_text)
    ai_inferred_app = str(parsed.get("ai_inferred_app") or "Worklog")
    ai_inferred_type = str(parsed.get("ai_inferred_type") or "feature")
    restored_at = datetime.now(timezone.utc).isoformat()
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"- created_at: {created_at}",
                "- source: David",
                "- status: raw",
                "- digest_status: not_digested",
                f"- restored_from_sprint_code: {sprint_code or ''}",
                f"- restored_at: {restored_at}",
                f"- restore_reason: {restore_reason}",
                f"- thought_fingerprint: {parsed.get('thought_id') or parsed.get('thought_fingerprint') or ''}",
                f"- raw_text: {raw_text}",
                f"- ai_inferred_app: {ai_inferred_app}",
                f"- ai_inferred_type: {ai_inferred_type}",
                f"- ai_summary: {ai_summary}",
                "",
                "## Raw Thought",
                raw_text,
                "",
            ]
        ),
        encoding="utf-8",
    )


def _rewrite_thought_created_at(path: Path, created_at: str) -> None:
    if not path.exists() or not created_at.strip():
        return
    text = path.read_text(encoding="utf-8")
    if re.search(r"^- created_at: .*?$", text, flags=re.M):
        text = re.sub(r"^- created_at: .*?$", f"- created_at: {created_at.strip()}", text, flags=re.M)
    else:
        text = text.replace("- source: David\n", f"- created_at: {created_at.strip()}\n- source: David\n", 1)
    path.write_text(text, encoding="utf-8")


def _thought_created_at_from_path(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        parsed = _parse_thought_file(path)
    except OSError:
        return ""
    return str(parsed.get("created_at") or "").strip()


def _canonicalize_source_thoughts(thoughts: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for thought in thoughts:
        if not isinstance(thought, dict):
            continue
        key = (
            str(thought.get("thought_id") or thought.get("thought_fingerprint") or "").strip().lower(),
            str(thought.get("path") or thought.get("source_thought_path") or "").strip().lower(),
            str(thought.get("normalized_summary") or thought.get("display_snippet") or thought.get("raw_text_full") or thought.get("title") or "").strip().lower(),
            str(thought.get("raw_text_full") or thought.get("raw_text") or thought.get("raw") or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(thought)
    return deduped


def _source_idea_strings(thoughts: list[dict[str, object]]) -> list[str]:
    deduped = _canonicalize_source_thoughts(thoughts)
    items: list[str] = []
    seen: set[str] = set()
    for thought in deduped:
        text = str(
            thought.get("normalized_summary")
            or thought.get("display_snippet")
            or thought.get("raw_text_full")
            or thought.get("title")
            or thought.get("path")
            or ""
        ).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    return items


def _dedupe_text_list(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _canonical_idea_count(
    source_ideas: list[str] | None = None,
    *,
    canonical_source_ideas: list[str] | None = None,
) -> int:
    if canonical_source_ideas is not None:
        return len(_dedupe_text_list([str(item) for item in canonical_source_ideas]))


def _sprint_duplicate_key_from_items(items: list[dict[str, object]]) -> str:
    canonical_items = _canonicalize_source_thoughts([item for item in items if isinstance(item, dict)])
    parts: list[str] = []
    thought_ids = sorted({str(_thought_item_fingerprint(item)).strip() for item in canonical_items if str(_thought_item_fingerprint(item)).strip()})
    if thought_ids:
        parts.append("ids:" + "|".join(thought_ids))
    paths = sorted({str(item.get("path") or "").strip() for item in canonical_items if str(item.get("path") or "").strip()})
    if paths:
        parts.append("paths:" + "|".join(paths))
    summaries = sorted({str(item.get("normalized_summary") or item.get("display_snippet") or item.get("title") or "").strip().lower() for item in canonical_items if str(item.get("normalized_summary") or item.get("display_snippet") or item.get("title") or "").strip()})
    if summaries:
        parts.append("summaries:" + "|".join(summaries))
    if not parts and canonical_items:
        parts.append("titles:" + "|".join(sorted({str(item.get("title") or "").strip().lower() for item in canonical_items if str(item.get("title") or "").strip()})))
    return "||".join(parts)


def _sprint_duplicate_key_from_record(record: dict[str, object]) -> str:
    parts: list[str] = []
    summaries = sorted({str(item).strip().lower() for item in (record.get("canonical_source_ideas") or record.get("source_idea_summaries") or record.get("source_ideas") or []) if str(item).strip()})
    if summaries:
        parts.append("summaries:" + "|".join(summaries))
    paths = sorted({str(item).strip() for item in (record.get("source_thought_paths") or []) if str(item).strip()})
    if paths:
        parts.append("paths:" + "|".join(paths))
    ids = sorted({str(item).strip() for item in (record.get("source_thought_ids") or record.get("selected_thought_ids") or []) if str(item).strip()})
    if ids:
        parts.append("ids:" + "|".join(ids))
    if not parts and summaries:
        parts.append("summaries:" + "|".join(summaries))
    return "||".join(parts)


def _existing_sprint_record_for_duplicate_key(duplicate_key: str) -> dict[str, object] | None:
    if not duplicate_key:
        return None
    for record in _sprint_records():
        if record.get("status_key") in {"rejected", "rescinded", "deleted"}:
            continue
        if _sprint_duplicate_key_from_record(record) == duplicate_key:
            return record
    return None


def _sprint_summary_signature_from_items(items: list[dict[str, object]]) -> str:
    canonical_items = _canonicalize_source_thoughts([item for item in items if isinstance(item, dict)])
    summaries = sorted({str(item.get("normalized_summary") or item.get("display_snippet") or item.get("title") or "").strip().lower() for item in canonical_items if str(item.get("normalized_summary") or item.get("display_snippet") or item.get("title") or "").strip()})
    return "||".join(summaries)


def _sprint_summary_signature_from_record(record: dict[str, object]) -> str:
    summaries = sorted({str(item).strip().lower() for item in (record.get("canonical_source_ideas") or record.get("source_idea_summaries") or record.get("source_ideas") or []) if str(item).strip() and str(item).strip().lower() != "none"})
    return "||".join(summaries)
    if source_ideas is not None:
        return len(_dedupe_text_list([str(item) for item in source_ideas]))
    return 0


def _restore_source_ideas_for_record(record: dict[str, object], restore_reason: str = "rescinded") -> tuple[list[str], list[str], dict[str, int]]:
    restored: list[str] = []
    warnings: list[str] = []
    counts = {"restored": 0, "already_active": 0, "recreated": 0, "missing": 0}
    candidates = list(dict.fromkeys([
        *[str(item) for item in record.get("proposed_source_thoughts", []) if str(item).strip()],
        *[str(item) for item in record.get("digested_source_thoughts", []) if str(item).strip()],
        *[str(item) for item in record.get("source_thought_paths", []) if str(item).strip()],
        *[str(item) for item in record.get("source_thoughts", []) if str(item).strip()],
    ]))
    summaries = [
        str(item)
        for item in (
            record.get("source_idea_summaries")
            or record.get("source_ideas")
            or []
        )
        if str(item).strip()
    ]
    created_ats = [
        str(item)
        for item in (
            record.get("source_created_ats")
            or []
        )
        if str(item).strip()
    ]
    sprint_code = str(record.get("sprint_code") or record.get("intended_sprint_code") or "")
    for index, source_path in enumerate(candidates):
        source_file = WORKLOG_ROOT / source_path.strip()
        already_active = source_file.exists() and source_file.parent == THOUGHT_BOX_DIR
        holding_file = None
        if not source_file.exists():
            for candidate in (_thought_proposed_dir() / source_file.name, _thought_digested_dir() / source_file.name):
                if candidate.exists():
                    holding_file = candidate
                    break
        created_at = _thought_created_at_from_path(source_file)
        if not created_at and holding_file:
            created_at = _thought_created_at_from_path(holding_file)
        if not created_at and created_ats:
            created_at = created_ats[min(index, len(created_ats) - 1)]
        restored_path, warning = _restore_source_thought_path(source_path)
        if restored_path:
            restored_file = WORKLOG_ROOT / restored_path
            source_summary = summaries[min(index, len(summaries) - 1)] if summaries else ""
            if created_at:
                _rewrite_thought_created_at(restored_file, created_at)
            restored.append(restored_path)
            if already_active:
                counts["already_active"] += 1
            elif source_file.exists():
                _normalize_restored_thought_file(restored_file, sprint_code, restore_reason, source_summary=source_summary)
                counts["restored"] += 1
            else:
                _normalize_restored_thought_file(restored_file, sprint_code, restore_reason, source_summary=source_summary)
                counts["recreated"] += 1
            continue
        source_summary = ""
        if summaries:
            source_summary = summaries[min(index, len(summaries) - 1)]
        recreated_path, recreate_warning = _recreate_restored_thought(source_path, source_summary, sprint_code, restore_reason, created_at=created_at)
        if recreated_path:
            counts["recreated"] += 1
            restored.append(recreated_path)
        else:
            counts["missing"] += 1
        if recreate_warning:
            warnings.append(recreate_warning)
        elif warning:
            warnings.append(warning)
    if not candidates and summaries:
        for index, summary in enumerate(summaries, start=1):
            created_at = created_ats[min(index - 1, len(created_ats) - 1)] if created_ats else ""
            recreated_path, recreate_warning = _recreate_restored_thought(
                f"restored-summary-{index}.md",
                summary,
                sprint_code,
                restore_reason,
                created_at=created_at,
            )
            if recreated_path:
                _normalize_restored_thought_file(WORKLOG_ROOT / recreated_path, sprint_code, restore_reason, source_summary=summary)
                restored.append(recreated_path)
                counts["recreated"] += 1
            if recreate_warning:
                warnings.append(recreate_warning)
    return restored, warnings, counts


def _move_handoff_record(record: dict[str, object], status: str) -> str:
    handoff_path = str(record.get("handoff_path") or "").strip()
    if not handoff_path:
        return ""
    source = WORKLOG_ROOT / handoff_path
    if not source.exists():
        return handoff_path
    _ensure_handoff_dirs()
    target_dir = _sprint_handoffs_dir() / status
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        target = target_dir / f"{source.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{source.suffix}"
    source.rename(target)
    return str(target.relative_to(WORKLOG_ROOT))


def _archive_sprint_record(record: dict[str, object], status: str) -> Path | None:
    source = WORKLOG_ROOT / str(record["path"])
    if not source.exists():
        return None
    target = _sprints_dir(status) / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return target


def _append_sprint_audit_note(path: Path, note_lines: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if "## Audit Trail" not in text:
        text += "\n## Audit Trail\n"
    text += "\n" + "\n".join(note_lines).strip() + "\n"
    text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {datetime.now(timezone.utc).isoformat()}", text, flags=re.M)
    path.write_text(text, encoding="utf-8")


def _parse_proposed_sprint_record(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    meta = _parse_key_value_metadata(text)
    sprint_id = meta.get("sprint_id") or meta.get("proposal_id") or path.stem.split("-", 1)[0]
    source_ideas = []
    proposed_work = []
    source_request_paths = []
    source_request_ids = []
    current_section = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            continue
        if current_section == "source ideas" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_ideas.append(value)
        elif current_section == "proposed source thoughts" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_ideas.append(value)
        elif current_section == "proposed work" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                proposed_work.append(value)
        elif current_section == "source request paths" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_request_paths.append(value)
        elif current_section == "source request ids" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_request_ids.append(value)
    return {
        "id": sprint_id,
        "sprint_id": sprint_id,
        "proposal_id": meta.get("proposal_id") or path.stem.split("-", 1)[0],
        "intended_sprint_code": meta.get("intended_sprint_code") or meta.get("sprint_code") or "",
        "sprint_group_name": meta.get("sprint_group_name") or path.stem.split("-", 1)[1].replace("-", " ").title(),
        "app_product": meta.get("app_product") or "Other",
        "scope": meta.get("scope") or "Small",
        "status": meta.get("status") or "proposed",
        "created_at": meta.get("created_at") or _format_file_timestamp(path),
        "updated_at": meta.get("updated_at") or _format_file_timestamp(path),
        "source_thought_ids": [item.strip() for item in (meta.get("source_thought_ids") or "").split(",") if item.strip()],
        "source_thought_paths": [item.strip() for item in (meta.get("source_thought_paths") or "").split(",") if item.strip()],
        "source_request_paths": source_request_paths,
        "source_request_ids": source_request_ids,
        "proposed_source_thoughts": [item.strip() for item in (meta.get("proposed_source_thoughts") or "").split(",") if item.strip()],
        "source_created_ats": [item.strip() for item in (meta.get("source_created_ats") or "").split(",") if item.strip()],
        "source_ideas": _dedupe_text_list(source_ideas),
        "source_idea_summaries": _dedupe_text_list(source_ideas),
        "canonical_source_ideas": _dedupe_text_list(source_ideas),
        "idea_count": _canonical_idea_count(canonical_source_ideas=_dedupe_text_list(source_ideas)),
        "proposed_work": _dedupe_text_list(proposed_work),
        "canonical_proposed_work": _dedupe_text_list(proposed_work),
        "purpose": meta.get("purpose") or _extract_section_text(text, "Purpose"),
        "starting_prompt": meta.get("starting_prompt") or _extract_section_text(text, "Codex/ChatGPT Starting Prompt"),
        "recommended_first_step": meta.get("recommended_first_step") or _extract_section_text(text, "Recommended First Step"),
        "handoff_md": _extract_section_text(text, "Handoff Preview"),
        "path": str(path.relative_to(WORKLOG_ROOT)),
        "raw_html": _render_markdown(text),
    }


def _proposed_sprint_records() -> list[dict[str, object]]:
    _ensure_sprint_dirs()
    records = [_parse_proposed_sprint_record(path) for path in sorted(_sprints_dir("proposed").glob("*.md"), reverse=True)]
    records.sort(key=lambda item: (item.get("updated_at", ""), item.get("created_at", ""), item.get("proposal_id", "")), reverse=True)
    return records


def _proposed_sprint_record_by_id(proposal_id: str) -> dict[str, object] | None:
    proposal_id = proposal_id.strip()
    for record in _proposed_sprint_records():
        record_id = str(record.get("proposal_id") or record.get("id") or "").strip()
        if record_id == proposal_id:
            return record
        path_stem = Path(str(record.get("path") or "")).stem
        if path_stem.startswith(proposal_id):
            return record
        if proposal_id and record_id.startswith(proposal_id):
            return record
    return None


def _remove_proposed_sprint_record(proposal_id: str, status: str = "rejected") -> Path | None:
    record = _proposed_sprint_record_by_id(proposal_id)
    if not record:
        return None
    source = WORKLOG_ROOT / str(record["path"])
    if not source.exists():
        return None
    if status == "rejected":
        target = _sprints_dir("rejected") / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        return target
    source.unlink()
    return source


def _reject_proposed_sprint_record(record: dict[str, object]) -> Path | None:
    proposal_id = str(record.get("id") or record.get("proposal_id") or "").strip()
    if not proposal_id:
        return None
    return _remove_proposed_sprint_record(proposal_id, "rejected")


def _approve_proposed_sprint_record(record: dict[str, object]) -> dict[str, object]:
    summary_signature = _sprint_summary_signature_from_record(record)
    existing_approved = None
    for candidate in _sprint_records():
        if candidate.get("status_key") != "approved":
            continue
        if candidate.get("proposal_id") == record.get("proposal_id") or candidate.get("id") == record.get("proposal_id") or candidate.get("proposal_id") == record.get("id"):
            existing_approved = candidate
            break
        if summary_signature and _sprint_summary_signature_from_record(candidate) == summary_signature:
            existing_approved = candidate
            break
    if existing_approved:
        return existing_approved
    active_thoughts = _thoughts_by_ids([str(item) for item in record.get("source_thought_ids", []) if str(item).strip()])
    if not active_thoughts:
        active_thoughts = _thoughts_by_paths([str(path) for path in record.get("source_thought_paths", [])])
    if not active_thoughts:
        proposed_paths = [
            str(_thought_proposed_dir() / Path(str(path)).name)
            for path in record.get("source_thought_paths", [])
            if str(path).strip()
        ]
        active_thoughts = _thoughts_by_paths(proposed_paths)
    if not active_thoughts and record.get("source_ideas"):
        wanted = {str(item).strip().lower() for item in record.get("source_ideas", []) if str(item).strip()}
        for item in _thought_box_items(digested_only=False):
            normalized = str(item.get("normalized_summary") or item.get("display_snippet") or item.get("title") or "").strip().lower()
            if normalized and normalized in wanted:
                active_thoughts.append(item)
    proposal = {
        **record,
        "source_thoughts": [item["path"] for item in active_thoughts],
        "source_thought_paths": [item["path"] for item in active_thoughts],
        "source_thought_ids": [_thought_item_fingerprint(item) for item in active_thoughts],
        "source_idea_summaries": [item.get("normalized_summary") or item.get("display_snippet") or item.get("title") for item in active_thoughts],
        "source_request_paths": [str(item.get("source_request_path") or "").strip() for item in active_thoughts if str(item.get("source_request_path") or "").strip()],
        "source_request_ids": [str(item.get("source_request_id") or item.get("source_request_path") or "").strip() for item in active_thoughts if str(item.get("source_request_id") or item.get("source_request_path") or "").strip()],
        "proposed_work": record.get("proposed_work") or [item.get("normalized_summary") or item.get("display_snippet") or item.get("title") for item in active_thoughts],
        "status": "approved",
    }
    sprint_record, handoff_path, sprint_path = _proposal_to_sprint_record(proposal)
    moved_for_group: list[str] = []
    sprint_record["digested_source_thoughts"] = moved_for_group
    if not active_thoughts:
        for source_path in [str(path) for path in record.get("source_thought_paths", []) if str(path).strip()]:
            source_file = WORKLOG_ROOT / source_path
            if not source_file.exists():
                source_file = _thought_proposed_dir() / Path(source_path).name
            if source_file.exists():
                active_thoughts.append({"path": source_path})
    for thought in active_thoughts:
        source_file = WORKLOG_ROOT / thought["path"]
        if not source_file.exists():
            source_file = _thought_proposed_dir() / Path(thought["path"]).name
        if not source_file.exists():
            continue
        destination = _move_thought(source_file, _thought_digested_dir())
        moved_for_group.append(str(destination.relative_to(WORKLOG_ROOT)))
    sprint_path.write_text(
        sprint_path.read_text(encoding="utf-8").replace(
            "## Digested Source Ideas\n- None",
            "## Digested Source Ideas\n" + ("\n".join(f"- {item}" for item in moved_for_group) if moved_for_group else "- None"),
        ),
        encoding="utf-8",
    )
    _remove_proposed_sprint_record(str(record.get("id") or record.get("proposal_id") or ""), "approved")
    sprint_record["digested_source_thoughts"] = moved_for_group
    return sprint_record


def _proposal_to_sprint_record(proposal: dict[str, object]) -> tuple[dict[str, object], Path, Path]:
    active_thoughts = _canonicalize_source_thoughts(_thoughts_by_ids([str(item) for item in proposal.get("source_thought_ids", []) if str(item).strip()]))
    if not active_thoughts:
        active_thoughts = _canonicalize_source_thoughts(_thoughts_by_paths([str(path) for path in proposal.get("source_thought_paths", [])]))
    if not active_thoughts and proposal.get("source_ideas"):
        wanted = {str(item).strip().lower() for item in proposal.get("source_ideas", []) if str(item).strip()}
        for item in _thought_box_items(digested_only=False):
            normalized = str(item.get("normalized_summary") or item.get("display_snippet") or item.get("title") or "").strip().lower()
            if normalized and normalized in wanted:
                active_thoughts.append(item)
        active_thoughts = _canonicalize_source_thoughts(active_thoughts)
    proposal_source_paths = [item["path"] for item in active_thoughts]
    proposal_source_ids = [_thought_item_fingerprint(item) for item in active_thoughts]
    proposal_source_summaries = _source_idea_strings(active_thoughts)
    if not proposal_source_summaries and proposal.get("source_ideas"):
        proposal_source_summaries = [str(item) for item in proposal.get("source_ideas", []) if str(item).strip()]
    if not proposal.get("proposed_work") and proposal_source_summaries:
        proposal = {**proposal, "proposed_work": proposal_source_summaries}
    sprint_code = str(proposal.get("intended_sprint_code") or proposal.get("sprint_code") or _generate_sprint_code(str(proposal.get("app_product") or "Other")))
    sprint_record = {
        **proposal,
        "status": "approved",
        "sprint_id": proposal.get("proposal_id") or proposal.get("sprint_id") or f"sp-{_sprint_id_prefix()}",
        "sprint_code": sprint_code,
        "created_at": proposal.get("created_at") or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "intended_sprint_code": sprint_code,
        "proposed_work": proposal.get("proposed_work") or [],
        "source_idea_summaries": proposal_source_summaries,
        "purpose": proposal.get("purpose") or "",
        "recommended_first_step": proposal.get("recommended_first_step") or "",
        "selected_thought_paths": proposal_source_paths,
        "selected_thought_ids": proposal_source_ids,
        "source_thought_paths": proposal_source_paths,
        "source_thought_ids": proposal_source_ids,
        "source_request_paths": sorted({str(item.get("source_request_path") or "").strip() for item in active_thoughts if str(item.get("source_request_path") or "").strip()}),
        "source_request_ids": sorted({str(item.get("source_request_id") or item.get("source_request_path") or "").strip() for item in active_thoughts if str(item.get("source_request_id") or item.get("source_request_path") or "").strip()}),
        "digested_source_thoughts": [],
    }
    handoff_path = _write_sprint_handoff_file(sprint_record)
    sprint_record["handoff_path"] = str(handoff_path.relative_to(WORKLOG_ROOT))
    sprint_path = _write_sprint_record(sprint_record, "approved")
    sprint_record["path"] = str(sprint_path.relative_to(WORKLOG_ROOT))
    sprint_record["id"] = sprint_record["sprint_id"]
    return sprint_record, handoff_path, sprint_path


def _sprint_record_path(status: str, sprint_id: str, title: str) -> Path:
    return _sprints_dir(status) / f"{sprint_id}-{_slugify_title(title)}.md"


def _sprint_id_prefix() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _sprint_code_prefix(app_product: str) -> str:
    return SPRINT_CODE_PREFIXES.get(_normalize_app_filter(app_product), "OTHER")


def _sprint_code_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _existing_sprint_codes() -> set[str]:
    codes = set()
    for record in _sprint_records():
        code = str(record.get("sprint_code") or "").strip().upper()
        if code:
            codes.add(code)
    return codes


def _generate_sprint_code(app_product: str, reserved_codes: set[str] | None = None) -> str:
    prefix = _sprint_code_prefix(app_product)
    date_stamp = _sprint_code_date()
    existing = _existing_sprint_codes()
    if reserved_codes:
        existing = existing.union({code.upper() for code in reserved_codes})
    for sequence in range(1, 1000):
        code = f"{prefix}-SPRINT-{date_stamp}-{sequence:03d}"
        if code not in existing:
            return code
    raise ValueError("Unable to generate a unique sprint code.")


def _sprint_code_from_record(record: dict[str, object]) -> str:
    code = str(record.get("sprint_code") or record.get("sprint_id") or "").strip().upper()
    if code.startswith("SP-"):
        code = code[3:]
    return code


def _update_sprint_record_text(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for key, value in updates.items():
        pattern = rf"^- {re.escape(key)}: .*?$"
        replacement = f"- {key}: {value}"
        if re.search(pattern, text, flags=re.M):
            text = re.sub(pattern, replacement, text, flags=re.M)
        else:
            insert_at = text.find("\n\n")
            if insert_at == -1:
                text += f"\n- {key}: {value}\n"
            else:
                text = text[: insert_at + 2] + f"- {key}: {value}\n" + text[insert_at + 2 :]
    path.write_text(text, encoding="utf-8")


def _write_sprint_record(group: dict[str, object], status: str = "approved") -> Path:
    _ensure_sprint_dirs()
    sprint_id = str(group.get("sprint_id") or f"sp-{_sprint_id_prefix()}")
    sprint_code = str(group.get("sprint_code") or _generate_sprint_code(str(group.get("app_product") or "Other")))
    title = str(group.get("sprint_group_name") or "Sprint")
    path = _sprint_record_path(status, sprint_id, title)
    source_thoughts = [str(item) for item in group.get("source_thoughts", [])]
    source_idea_summaries = [str(item) for item in group.get("source_idea_summaries", [])]
    source_thought_paths = [str(item) for item in group.get("source_thought_paths", [])]
    source_request_paths = [str(item) for item in group.get("source_request_paths", [])]
    source_request_ids = [str(item) for item in group.get("source_request_ids", [])]
    digested_thoughts = [str(item) for item in group.get("digested_source_thoughts", [])]
    canonical_source_ideas = [str(item) for item in group.get("canonical_source_ideas", [])]
    app_product = str(group.get("app_product") or "Other")
    handoff_path = str(group.get("handoff_path") or "")
    text = "\n".join(
        [
            f"# Sprint Queue Record: {title}",
            "",
            f"- sprint_id: {sprint_id}",
            f"- proposal_id: {group.get('proposal_id') or ''}",
            f"- sprint_code: {sprint_code}",
            f"- app_product: {app_product}",
            f"- sprint_group_name: {title}",
            f"- status: {status}",
            f"- scope: {group.get('scope') or 'Small'}",
            f"- idea_count: {_canonical_idea_count(canonical_source_ideas=canonical_source_ideas or source_idea_summaries or source_thoughts)}",
            f"- created_at: {group.get('created_at') or datetime.now(timezone.utc).isoformat()}",
            f"- updated_at: {datetime.now(timezone.utc).isoformat()}",
            f"- handoff_path: {handoff_path}",
            f"- purpose: {group.get('purpose') or ''}",
            f"- recommended_first_step: {group.get('recommended_first_step') or ''}",
            f"- internal_release_notes: {group.get('internal_release_notes') or ''}",
            f"- plain_english_release_notes: {group.get('plain_english_release_notes') or ''}",
            f"- source_request_paths: {', '.join(source_request_paths)}",
            f"- source_request_ids: {', '.join(source_request_ids)}",
            "",
            "## Source Ideas",
            *([f"- {item}" for item in source_idea_summaries] or [f"- {item}" for item in source_thoughts] or ["- None"]),
            "",
            "## Source Thought Paths",
            *([f"- {item}" for item in source_thought_paths] or ["- None"]),
            "",
            "## Source Request Paths",
            *([f"- {item}" for item in source_request_paths] or ["- None"]),
            "",
            "## Source Request IDs",
            *([f"- {item}" for item in source_request_ids] or ["- None"]),
            "",
            "## Source Idea Summaries",
            *([f"- {item}" for item in source_idea_summaries] or ["- None"]),
            "",
            "## Internal Release Notes",
            str(group.get("internal_release_notes") or "Not recorded yet"),
            "",
            "## Plain English Release Notes",
            str(group.get("plain_english_release_notes") or "Not recorded yet"),
            "",
            "## Digested Source Ideas",
            *([f"- {item}" for item in digested_thoughts] or ["- None"]),
            "",
            "## Proposed Work",
            *([f"- {item}" for item in group.get('proposed_work', [])] or ["- Triage raw ideas into a focused sprint slice."]),
            "",
            "## Handoff Markdown",
            f"{group.get('handoff_path') or ''}",
            "",
            "## Codex/ChatGPT Starting Prompt",
            str(group.get("starting_prompt") or ""),
            "",
            "## Completion Requirement",
            f"When this sprint is complete, update Worklog using Sprint Code {sprint_code}.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8")
    return path


def _parse_sprint_record(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    meta = _parse_key_value_metadata(text)
    status = meta.get("status") or path.parent.name
    app_product = meta.get("app_product") or "Other"
    stem_parts = path.stem.split("-")
    if status == "proposed" and len(stem_parts) >= 4 and stem_parts[0] == "pr":
        sprint_id = "-".join(stem_parts[:3])
    else:
        sprint_id = meta.get("sprint_id") or meta.get("proposal_id") or path.stem.split("-", 1)[0]
    title = meta.get("title")
    if not title:
        title = meta.get("sprint_group_name")
    if status == "proposed" and not title and len(stem_parts) > 3:
        title = " ".join(part.title() for part in stem_parts[3:])
    if not title:
        for line in text.splitlines():
            if line.startswith("# Sprint Queue Record: "):
                title = line.split(":", 1)[1].strip()
                break
            if line.startswith("# Proposed Sprint Group: "):
                title = line.split(":", 1)[1].strip()
                break
    if not title:
        title = path.stem.split("-", 1)[1].replace("-", " ").title() if "-" in path.stem else path.stem.title()
    source_thoughts = []
    source_thought_paths = []
    source_ideas = []
    source_idea_summaries = []
    source_request_paths = []
    source_request_ids = []
    digested_source_thoughts = []
    proposed_work = []
    internal_release_notes = ""
    plain_english_release_notes = ""
    current_section = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            continue
        if current_section in {"source ideas", "source thought(s)"} and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_thoughts.append(value)
                if current_section == "source ideas":
                    source_ideas.append(value)
        elif current_section == "source thought paths" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_thought_paths.append(value)
        elif current_section == "source idea summaries" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_idea_summaries.append(value)
        elif current_section == "source request paths" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_request_paths.append(value)
        elif current_section == "source request ids" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                source_request_ids.append(value)
        elif current_section == "digested source ideas" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                digested_source_thoughts.append(value)
        elif current_section == "proposed work" and line.startswith("- "):
            value = line[2:].strip()
            if value and value.lower() != "none":
                proposed_work.append(value)
        elif current_section == "internal release notes":
            if line.strip():
                internal_release_notes = (internal_release_notes + "\n" + line.strip()).strip()
        elif current_section == "plain english release notes":
            if line.strip():
                plain_english_release_notes = (plain_english_release_notes + "\n" + line.strip()).strip()
    handoff_path = meta.get("handoff_path") or ""
    handoff_markdown = ""
    if handoff_path:
        handoff_file = WORKLOG_ROOT / str(handoff_path)
        if handoff_file.exists():
            handoff_markdown = handoff_file.read_text(encoding="utf-8")
    return {
        "id": sprint_id,
        "proposal_id": meta.get("proposal_id") or "",
        "sprint_code": meta.get("intended_sprint_code") or meta.get("sprint_code") or sprint_id.upper(),
        "intended_sprint_code": meta.get("intended_sprint_code") or meta.get("sprint_code") or sprint_id.upper(),
        "title": title,
        "sprint_group_name": meta.get("sprint_group_name") or title,
        "app_product": app_product,
        "status": status.title(),
        "status_key": status.lower(),
        "idea_count": _canonical_idea_count(
            canonical_source_ideas=_dedupe_text_list(source_idea_summaries or source_ideas or source_thoughts)
        ),
        "scope": meta.get("scope") or "Small",
        "created_at": meta.get("created_at") or _format_file_timestamp(path),
        "updated_at": meta.get("updated_at") or _format_file_timestamp(path),
        "path": str(path.relative_to(WORKLOG_ROOT)),
        "source_thoughts": _dedupe_text_list(source_thoughts),
        "source_ideas": _dedupe_text_list(source_ideas),
        "source_thought_paths": source_thought_paths,
        "source_request_paths": source_request_paths,
        "source_request_ids": source_request_ids,
        "source_idea_summaries": _dedupe_text_list(source_idea_summaries or source_ideas or source_thoughts),
        "canonical_source_ideas": _dedupe_text_list(source_idea_summaries or source_ideas or source_thoughts),
        "digested_source_thoughts": digested_source_thoughts,
        "proposed_work": _dedupe_text_list(proposed_work or source_idea_summaries or source_ideas or source_thoughts),
        "canonical_proposed_work": _dedupe_text_list(proposed_work or source_idea_summaries or source_ideas or source_thoughts),
        "handoff_path": handoff_path,
        "handoff_markdown": handoff_markdown,
        "handoff_md": _extract_section_text(text, "Handoff Preview"),
        "internal_release_notes": meta.get("internal_release_notes") or internal_release_notes,
        "plain_english_release_notes": meta.get("plain_english_release_notes") or plain_english_release_notes,
        "raw_html": _render_markdown(text),
        "starting_prompt": meta.get("starting_prompt") or _extract_section_text(text, "Codex/ChatGPT Starting Prompt"),
        "completion_requirement": meta.get("completion requirement") or _extract_section_text(text, "Completion Requirement"),
        "purpose": meta.get("purpose") or _extract_section_text(text, "Purpose"),
        "recommended_first_step": meta.get("recommended_first_step") or _extract_section_text(text, "Recommended First Step"),
        "done_at": meta.get("done_at") or "",
        "done_source": meta.get("done_source") or "",
        "reconciliation_pending": "## Reconciliation Pending" in text,
    }


def _set_sprint_status(record: dict[str, object], status: str) -> Path:
    status = status.strip().lower()
    if status not in {"proposed", "approved", "active", "completed", "staged", "shipped", "done", "reconciled"}:
        raise ValueError(f"Unsupported sprint status: {status}")
    record_path = WORKLOG_ROOT / str(record["path"])
    new_path = _update_sprint_record(record_path, status)
    record["status_key"] = status
    record["status"] = status.title()
    record["path"] = str(new_path.relative_to(WORKLOG_ROOT))
    return new_path


def _mark_sprint_done(record: dict[str, object], performed_by: str = "ui") -> Path:
    record_path = WORKLOG_ROOT / str(record["path"])
    done_at = datetime.now(timezone.utc).isoformat()
    text = record_path.read_text(encoding="utf-8")
    if "## Reconciliation Pending" not in text:
        text += (
            "\n## Reconciliation Pending\n"
            "\nThis sprint was marked done from the UI and requires Codex reconciliation.\n"
        )
    text = re.sub(r"^- status: .*?$", "- status: done", text, flags=re.M)
    if re.search(r"^- done_at: .*?$", text, flags=re.M):
        text = re.sub(r"^- done_at: .*?$", f"- done_at: {done_at}", text, flags=re.M)
    else:
        insert_at = text.find("\n\n")
        if insert_at == -1:
            text += f"\n- done_at: {done_at}\n- done_source: ui\n"
        else:
            text = text[: insert_at + 2] + f"- done_at: {done_at}\n- done_source: ui\n" + text[insert_at + 2 :]
    if re.search(r"^- done_source: .*?$", text, flags=re.M):
        text = re.sub(r"^- done_source: .*?$", "- done_source: ui", text, flags=re.M)
    text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {done_at}", text, flags=re.M)
    target = _sprints_dir("done") / record_path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.write_text(text, encoding="utf-8")
        if record_path != target and record_path.exists():
            record_path.unlink()
    else:
        record_path.rename(target)
        target.write_text(text, encoding="utf-8")
    record["status_key"] = "done"
    record["status"] = "Done"
    record["path"] = str(target.relative_to(WORKLOG_ROOT))
    record["done_at"] = done_at
    record["done_source"] = performed_by
    record["reconciliation_pending"] = True
    return target


def _resolve_sprint_source_thoughts(record: dict[str, object]) -> list[dict[str, str]]:
    thoughts = _canonicalize_source_thoughts(_thoughts_by_ids([str(item) for item in record.get("source_thought_ids", []) if str(item).strip()]))
    if thoughts:
        return thoughts
    thoughts = _canonicalize_source_thoughts(_thoughts_by_paths([str(item) for item in record.get("source_thought_paths", []) if str(item).strip()]))
    if thoughts:
        return thoughts
    wanted = {str(item).strip().lower() for item in record.get("source_idea_summaries", []) if str(item).strip()}
    if not wanted:
        wanted = {str(item).strip().lower() for item in record.get("source_thoughts", []) if str(item).strip()}
    matched: list[dict[str, str]] = []
    if wanted:
        for item in _thought_box_items(digested_only=False):
            normalized = str(item.get("normalized_summary") or item.get("display_snippet") or item.get("raw_text_full") or item.get("title") or "").strip().lower()
            if normalized and normalized in wanted:
                matched.append(item)
        matched = _canonicalize_source_thoughts(matched)
    if matched:
        return matched
    fallback_texts = [str(item).strip() for item in record.get("source_idea_summaries", []) if str(item).strip()]
    if not fallback_texts:
        fallback_texts = [str(item).strip() for item in record.get("source_thoughts", []) if str(item).strip()]
    return [
        {
            "path": "",
            "title": text,
            "raw_text_full": text,
            "normalized_summary": text,
            "display_snippet": text,
        }
        for text in fallback_texts
    ]


def _regenerate_sprint_handoff_record(record: dict[str, object]) -> tuple[dict[str, object], Path, Path]:
    fallback_texts = [str(item).strip() for item in record.get("source_idea_summaries", []) if str(item).strip()]
    fallback_paths = [str(item).strip() for item in record.get("source_thought_paths", []) if str(item).strip()]
    if fallback_texts:
        thoughts = [
            {
                "path": fallback_paths[index] if index < len(fallback_paths) else "",
                "title": text,
                "raw_text_full": text,
                "normalized_summary": text,
                "display_snippet": text,
            }
            for index, text in enumerate(fallback_texts)
        ]
    else:
        thoughts = _resolve_sprint_source_thoughts(record)
        if not thoughts:
            fallback_texts = [str(item).strip() for item in record.get("source_thoughts", []) if str(item).strip()]
            thoughts = [
                {
                    "path": fallback_paths[index] if index < len(fallback_paths) else "",
                    "title": text,
                    "raw_text_full": text,
                    "normalized_summary": text,
                    "display_snippet": text,
                }
                for index, text in enumerate(fallback_texts)
            ]
    sprint_group = {
        **record,
        "sprint_id": record.get("sprint_id") or record.get("id") or "",
        "thoughts": thoughts,
        "source_thoughts": [thought["path"] for thought in thoughts],
        "source_thought_paths": [thought["path"] for thought in thoughts],
        "source_thought_ids": [_thought_item_fingerprint(thought) for thought in thoughts],
        "source_idea_summaries": [thought.get("normalized_summary") or thought.get("raw_text_full") or thought.get("display_snippet") or thought.get("title") for thought in thoughts],
        "proposed_work": record.get("proposed_work") or [thought.get("normalized_summary") or thought.get("raw_text_full") or thought.get("display_snippet") or thought.get("title") for thought in thoughts],
        "purpose": record.get("purpose") or (f"Turn {record.get('app_product') or 'Worklog'} ideas into a focused sprint-sized implementation conversation."),
        "recommended_first_step": record.get("recommended_first_step") or (thoughts[0].get("normalized_summary") if thoughts else "Review the source ideas and outline the smallest implementation slice."),
    }
    handoff_markdown = _build_handoff_markdown_from_record(sprint_group, thoughts)
    handoff_path_value = str(record.get("handoff_path") or "").strip()
    handoff_path = WORKLOG_ROOT / handoff_path_value if handoff_path_value else Path()
    if not handoff_path_value or not handoff_path.exists():
        handoff_path = _sprint_handoffs_dir() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{_slugify_title(str(record.get('title') or record.get('sprint_group_name') or 'sprint'))}.md"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(handoff_markdown, encoding="utf-8")
    sprint_group["handoff_path"] = str(handoff_path.relative_to(WORKLOG_ROOT))
    sprint_group["handoff_markdown"] = handoff_markdown
    sprint_path = _write_sprint_record(sprint_group, str(record.get("status_key") or "approved"))
    sprint_group["path"] = str(sprint_path.relative_to(WORKLOG_ROOT))
    sprint_group["id"] = sprint_group.get("sprint_id")
    return sprint_group, handoff_path, sprint_path


def _existing_sprint_record_for_proposal_duplicate(record: dict[str, object]) -> dict[str, object] | None:
    duplicate_key = _sprint_duplicate_key_from_record(record)
    if not duplicate_key:
        return None
    return _existing_sprint_record_for_duplicate_key(duplicate_key)


def _write_sprint_handoff_file(group: dict[str, object]) -> Path:
    _sprint_handoffs_dir().mkdir(parents=True, exist_ok=True)
    title = str(group.get("sprint_group_name") or "Sprint Handoff")
    path = _sprint_handoffs_dir() / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}-{_slugify_title(title)}.md"
    path.write_text(_build_handoff_markdown_from_record(group, group.get("thoughts") or []), encoding="utf-8")
    return path


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
    raw_section_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("# ") and not data.get("title"):
            data["title"] = line[2:].strip()
        if line.startswith("- "):
            if ":" in line[2:]:
                key, value = line[2:].split(":", 1)
                data[key.strip().lower().replace(" ", "_")] = value.strip()
        elif line.startswith("## "):
            current = line[3:].strip().lower().replace(" ", "_")
            data.setdefault(current, "")
        elif current and line.strip():
            data[current] = (data.get(current, "") + "\n" + line).strip()
            if current == "raw_thought":
                raw_section_lines.append(line.strip())
    data["title"] = data.get("title") or path.stem.replace("-", " ").title()
    data["display_title"] = _clean_thought_title(data["title"])
    raw_text_full = data.get("raw_thought") or data.get("raw_text") or data.get("raw") or "\n".join(raw_section_lines)
    data["raw_text_full"] = raw_text_full.strip()
    data["raw_text"] = data["raw_text_full"]
    raw_lines = []
    for line in data["raw_text_full"].splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#") or cleaned.startswith("- "):
            continue
        if re.match(r"^\d{4}-\d{2}-\d{2}", cleaned):
            continue
        raw_lines.append(cleaned)
    data["display_snippet"] = " ".join(raw_lines[:3]).strip()
    data["normalized_summary"] = _normalize_idea_summary(data["raw_text_full"], data["title"], data["path"])
    created_at_value = data.get("created_at") or data.get("created") or ""
    created_dt: datetime | None = None
    if created_at_value:
        try:
            created_dt = datetime.fromisoformat(str(created_at_value).replace("Z", "+00:00"))
        except ValueError:
            created_dt = None
    created_dt = created_dt or datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    data["created_display"] = _format_pacific_date_short(created_dt)
    data["created_full_display"] = _format_local_timestamp(created_dt)
    data["thought_id"] = data.get("thought_fingerprint") or hashlib.sha256(data.get("raw_text_full", "").strip().encode("utf-8")).hexdigest()[:16]
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


def _update_thought_file(path: Path, updates: dict[str, str]) -> None:
    item = _parse_thought_file(path)
    title = updates.get("title") or item.get("title") or path.stem.replace("-", " ").title()
    raw_text = updates.get("raw_text") if updates.get("raw_text") is not None else item.get("raw_text_full") or ""
    ai_inferred_app = updates.get("ai_inferred_app") or item.get("ai_inferred_app") or "Other"
    ai_inferred_type = updates.get("ai_inferred_type") or item.get("ai_inferred_type") or "feature"
    ai_summary = updates.get("ai_summary") or item.get("ai_summary") or item.get("normalized_summary") or raw_text
    created_at = updates.get("created_at") or item.get("created_at") or item.get("created") or ""
    source = updates.get("source") or item.get("source") or "David"
    thought_fingerprint = updates.get("thought_fingerprint") or item.get("thought_fingerprint") or ""
    source_inbox_path = updates.get("source_inbox_path") or item.get("source_inbox_path") or ""
    source_request_path = updates.get("source_request_path") or item.get("source_request_path") or ""
    source_request_id = updates.get("source_request_id") or item.get("source_request_id") or ""
    source_request_title = updates.get("source_request_title") or item.get("source_request_title") or ""
    lines = [
        f"# {title}",
        "",
        f"- created_at: {created_at}" if created_at else None,
        f"- source: {source}",
        f"- source_inbox_path: {source_inbox_path}" if source_inbox_path else None,
        f"- source_request_path: {source_request_path}" if source_request_path else None,
        f"- source_request_id: {source_request_id}" if source_request_id else None,
        f"- source_request_title: {source_request_title}" if source_request_title else None,
        f"- status: {updates.get('status') or item.get('status') or 'raw'}",
        f"- digest_status: {updates.get('digest_status') or item.get('digest_status') or 'not_digested'}",
        f"- thought_fingerprint: {thought_fingerprint}" if thought_fingerprint else None,
        f"- raw_text: {raw_text}",
        f"- ai_inferred_app: {ai_inferred_app}",
        f"- ai_inferred_type: {ai_inferred_type}",
        f"- ai_summary: {ai_summary}",
        "",
        "## Raw Thought",
        raw_text,
        "",
    ]
    path.write_text("\n".join(line for line in lines if line is not None), encoding="utf-8")


def _move_thought(path: Path, destination_dir: Path) -> Path:
    _ensure_thought_box_dir()
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    if destination.exists():
        stem = destination.stem
        suffix = destination.suffix or ".md"
        for index in range(2, 1000):
            candidate = destination_dir / f"{stem}-restored-{index:03d}{suffix}"
            if not candidate.exists():
                destination = candidate
                break
    shutil.move(str(path), str(destination))
    return destination


def _thought_item_fingerprint(item: dict[str, str]) -> str:
    return item.get("thought_id") or item.get("thought_fingerprint") or hashlib.sha256(item.get("raw_text", "").strip().encode("utf-8")).hexdigest()[:16]


def _clean_idea_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" -:\t")
    cleaned = re.sub(r"^(raw thought|thought|idea)\s*[:\-]\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(on\s+)?worklog\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^\d{4}[-/ ]\d{2}[-/ ]\d{2}[\sT]?\d{2}:?\d{2}(?::\d{2})?\s*", "", cleaned)
    cleaned = re.sub(r"^\d{4}\s+\d{2}\s+\d{2}\s+\d{6}\s*", "", cleaned)
    cleaned = re.sub(r"^\d{4}\s+\d{2}\s+\d{2}\s*", "", cleaned)
    cleaned = re.sub(r"^(please|should|would like to|want to|need to|let's)\s+", "", cleaned, flags=re.I)
    return cleaned.strip()


def _normalize_idea_summary(raw_text: str, title: str = "", path: str = "") -> str:
    text = _clean_idea_text(raw_text or "")
    lowered = f"{title} {path} {text}".lower()
    if not text:
        return title or Path(path).stem.replace("-", " ").title() or "Worklog idea"
    if "sprint queue" in lowered and "filter" in lowered and ("auto" in lowered or "apply" in lowered):
        return "Inbox and Sprint Queue filters should auto-apply when changed."
    if any(phrase in lowered for phrase in ["inbox / new /bugs / features / support / closed", "inbox new bugs features support closed", "category clutter"]):
        return "Simplify the Inbox navigation and reduce visible category clutter."
    if "idea inventory" in lowered and "created" in lowered and ("pst" in lowered or "date / time" in lowered or "raw thought" in lowered):
        return "Improve Idea Inventory table readability with short local timestamps and cleaner raw-thought text."
    if "raw thought" in lowered and "date / time" in lowered:
        return "Improve Idea Inventory readability by keeping raw thoughts clean and using short local timestamps."
    if "worklog" in lowered and "report" in lowered and "idea inventory" in lowered:
        return "Simplify Worklog reporting and queue workflows by improving filtering and Idea Inventory scanning."
    text = re.sub(r"\bwe only need to\b", "", text, flags=re.I).strip()
    text = re.sub(r"\bshould\s+n\b", "should", text, flags=re.I)
    if not text.endswith("."):
        text += "."
    return text[0].upper() + text[1:]


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


def _thoughts_by_ids(ids: list[str]) -> list[dict[str, str]]:
    wanted = set(ids)
    items = []
    for item in _thought_box_items(digested_only=False):
        if _thought_item_fingerprint(item) in wanted:
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
    preview["source_idea_summaries"] = [item.get("normalized_summary") or item.get("display_snippet") or item.get("title") for item in items]
    preview["source_thought_ids"] = [_thought_item_fingerprint(item) for item in items]
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


def _validation_session_records() -> list[dict[str, object]]:
    root = validation_session_store.session_dir(WORKLOG_ROOT)
    if not root.exists():
        return []
    records: list[dict[str, object]] = []
    for path in sorted(root.glob("*.md"), reverse=True):
        try:
            data = validation_session_store.parse_session(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        counts = validation_session_store.session_status_counts(data)
        records.append(
            {
                "path": str(path.relative_to(WORKLOG_ROOT)),
                "slug": str(data.get("slug") or path.stem),
                "title": str(data.get("title") or path.stem.replace("-", " ").title()),
                "app": str(data.get("app") or ""),
                "run": str(data.get("run") or ""),
                "track": str(data.get("track") or ""),
                "release": str(data.get("release") or ""),
                "status": str(data.get("status") or "in_progress"),
                "updated_at": str(data.get("updated_at") or ""),
                "completed_at": str(data.get("completed_at") or ""),
                "blocked_at": str(data.get("blocked_at") or ""),
                "pass_count": counts.get("pass", 0),
                "fail_count": counts.get("fail", 0),
                "blocked_count": counts.get("blocked", 0),
                "pending_count": counts.get("pending", 0),
                "total_items": len(data.get("items") or []),
            }
        )
    return records


def _validation_session_record_by_slug(slug: str) -> tuple[Path, dict[str, object]] | tuple[None, None]:
    path = validation_session_store.session_path(WORKLOG_ROOT, slug)
    if not path.exists():
        return None, None
    return path, validation_session_store.parse_session(path.read_text(encoding="utf-8"))


def _validation_session_apply_form(data: dict[str, object], form: dict[str, str], *, item_id: str | None = None) -> dict[str, object]:
    items = list(data.get("items") or [])
    target_ids = [item_id] if item_id else [str(item.get("id") or "") for item in items]
    for current_id in target_ids:
        if not current_id:
            continue
        updates = {
            "status": form.get(f"item_status_{current_id}") or None,
            "notes": form.get(f"item_notes_{current_id}") or None,
            "finding_severity": form.get(f"item_finding_severity_{current_id}") or None,
            "finding_summary": form.get(f"item_finding_summary_{current_id}") or None,
        }
        data = validation_session_store.update_item(data, current_id, updates)
    final_recommendation = (form.get("final_recommendation") or "").strip()
    if final_recommendation:
        data["final_recommendation"] = final_recommendation
    session_status = (form.get("session_status") or "").strip()
    if session_status in validation_session_store.ALLOWED_SESSION_STATUSES:
        data["status"] = session_status
        if session_status == "completed":
            data = validation_session_store.complete_session(data)
        else:
            data["updated_at"] = validation_session_store.now_iso()
    return data


def _validation_session_form_flag(form: dict[str, str], key: str, default: bool = True) -> bool:
    value = form.get(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "checked"}


def _validation_session_request_value(name: str, default: str = "") -> str:
    return (request.form.get(name) or request.args.get(name) or default).strip()


def _validation_session_trace_snapshot(record: dict[str, object]) -> dict[str, object]:
    items = list(record.get("items") or [])
    return {
        "path": str(record.get("_path") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "item_count": len(items),
        "counts": dict(validation_session_store.session_status_counts(record)),
        "first_statuses": [str(item.get("status") or "pending") for item in items[:5]],
        "first_ids": [str(item.get("id") or "") for item in items[:10]],
    }


def _sprint_records() -> list[dict[str, object]]:
    _ensure_sprint_dirs()
    records = []
    for status in ["proposed", "rescinded", "deleted", "approved", "active", "completed", "staged", "shipped", "done", "reconciled"]:
        for path in sorted(_sprints_dir(status).glob("*.md"), reverse=True):
            record = _parse_sprint_record(path)
            record["status_key"] = status
            record["status"] = status.title()
            records.append(record)
    records.sort(key=lambda item: (item.get("updated_at", ""), item.get("created_at", ""), item.get("id", "")), reverse=True)
    return records


def _terminal_sprint_status_rank(status_key: str) -> int:
    order = {
        "shipped": 0,
        "reconciled": 1,
        "done": 2,
        "staged": 3,
        "completed": 4,
        "active": 5,
        "approved": 6,
        "proposed": 7,
        "rescinded": 8,
        "deleted": 9,
    }
    return order.get(status_key, 99)


def _sprint_code_duplicates() -> dict[str, list[dict[str, object]]]:
    duplicates: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in _sprint_records():
        code = str(record.get("sprint_code") or "").strip().upper()
        if code:
            duplicates[code].append(record)
    return {code: records for code, records in duplicates.items() if len(records) > 1}


def _sprint_duplicate_report_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for code, records in sorted(_sprint_code_duplicates().items()):
        rows.append(
            {
                "sprint_code": code,
                "records": [
                    {
                        "path": record.get("path"),
                        "status": record.get("status_key"),
                        "created_at": record.get("created_at"),
                        "done_at": record.get("done_at"),
                        "shipped_at": record.get("shipped_at"),
                    }
                    for record in records
                ],
                "canonical_path": _sprint_duplicate_canonical_record(records).get("path") if _sprint_duplicate_canonical_record(records) else "",
            }
        )
    return rows


def _sprint_duplicate_canonical_record(records: list[dict[str, object]]) -> dict[str, object] | None:
    if not records:
        return None
    non_terminal = [record for record in records if record.get("status_key") in {"proposed", "approved", "active", "completed", "staged"}]
    if len(non_terminal) == 1:
        return non_terminal[0]
    if len(non_terminal) > 1:
        return None
    ranked = sorted(records, key=lambda record: (
        _terminal_sprint_status_rank(str(record.get("status_key") or "")),
        str(record.get("done_at") or record.get("shipped_at") or ""),
        str(record.get("updated_at") or ""),
        str(record.get("created_at") or ""),
        str(record.get("path") or ""),
    ))
    return ranked[0] if ranked else None


def _sprint_duplicate_resolution_warning(records: list[dict[str, object]], canonical: dict[str, object] | None) -> str:
    paths = ", ".join(str(record.get("path") or "") for record in records if str(record.get("path") or "").strip())
    if canonical:
        return f"Duplicate sprint code resolved to {canonical.get('path') or 'a canonical record'}; other matches: {paths}."
    return f"Duplicate sprint code conflict across: {paths}."


def _sprint_duplicate_match_details(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "path": record.get("path"),
            "status": record.get("status_key"),
            "created_at": record.get("created_at"),
            "done_at": record.get("done_at"),
            "shipped_at": record.get("shipped_at"),
        }
        for record in records
    ]


def _annotate_sprint_duplicate(record: dict[str, object], canonical: dict[str, object]) -> None:
    record_path = WORKLOG_ROOT / str(record["path"])
    canonical_path = str(canonical.get("path") or canonical.get("sprint_code") or "")
    note = "\n".join(
        [
            "",
            "## Duplicate Resolution",
            f"- superseded_by: {canonical_path}",
            f"- duplicate_resolution_note: Superseded by canonical sprint code lookup for {record.get('sprint_code') or ''}.",
            f"- resolved_at: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]
    )
    text = record_path.read_text(encoding="utf-8")
    if "## Duplicate Resolution" not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += note
        text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {datetime.now(timezone.utc).isoformat()}", text, flags=re.M)
        record_path.write_text(text, encoding="utf-8")


def _move_sprint_to_duplicates(record: dict[str, object], canonical: dict[str, object]) -> Path | None:
    source = WORKLOG_ROOT / str(record["path"])
    if not source.exists():
        return None
    target_dir = _sprints_dir("duplicates")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists():
        target = target_dir / f"{source.stem}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{source.suffix}"
    source.rename(target)
    record_path = target
    text = record_path.read_text(encoding="utf-8")
    if "## Duplicate Resolution" not in text:
        text += "\n## Duplicate Resolution\n"
        text += f"- superseded_by: {canonical.get('path') or canonical.get('sprint_code') or ''}\n"
        text += f"- duplicate_resolution_note: Superseded by canonical sprint code lookup for {record.get('sprint_code') or ''}.\n"
        text += f"- resolved_at: {datetime.now(timezone.utc).isoformat()}\n"
        text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {datetime.now(timezone.utc).isoformat()}", text, flags=re.M)
        record_path.write_text(text, encoding="utf-8")
    return target


def _filter_sprint_records(records: list[dict[str, object]], status: str, app_slug: str) -> list[dict[str, object]]:
    status = (status or "all").lower()
    app_slug = _normalize_app_filter(app_slug)
    if status == "all":
        filtered = [record for record in records if record.get("status_key") not in {"rescinded", "deleted", "done", "reconciled"}]
    else:
        filtered = [record for record in records if record.get("status_key") == status]
    if app_slug != "all":
        filtered = [record for record in filtered if _normalize_app_filter(str(record.get("app_product") or "")) == app_slug]
    return filtered


def _sprint_counts_by_app() -> dict[str, dict[str, int]]:
    counts = {app: {"proposed": 0, "approved": 0, "active": 0, "completed": 0, "staged": 0, "shipped": 0, "done": 0} for app in APP_FILTERS.values()}
    for record in _sprint_records():
        app = record.get("app_product") or "Other"
        if app not in counts:
            counts[app] = {"proposed": 0, "approved": 0, "active": 0, "completed": 0, "staged": 0, "shipped": 0, "done": 0}
        key = str(record.get("status_key") or "proposed")
        if key in counts[app]:
            counts[app][key] += 1
    return counts


def _update_sprint_record(record_path: Path, status: str) -> Path:
    text = record_path.read_text(encoding="utf-8")
    text = re.sub(r"^- status: .*?$", f"- status: {status}", text, flags=re.M)
    text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {datetime.now(timezone.utc).isoformat()}", text, flags=re.M)
    target_dir = _sprints_dir(status)
    target_dir.mkdir(parents=True, exist_ok=True)
    new_path = target_dir / record_path.name
    if new_path != record_path:
        record_path.rename(new_path)
    new_path.write_text(text, encoding="utf-8")
    if status == "shipped":
        try:
            record = _parse_sprint_record(new_path)
            _create_request_live_notifications_for_sprint(record)
        except Exception:
            pass
    if status == "completed":
        try:
            _generate_release_notes_draft(new_path)
        except Exception:
            pass
    return new_path


def _append_sprint_completion_notes(record_path: Path, notes: str) -> Path:
    text = record_path.read_text(encoding="utf-8")
    if "## Completion Notes" not in text:
        text += "\n## Completion Notes\n"
    text += f"\n{notes.strip()}\n"
    text = re.sub(r"^- updated_at: .*?$", f"- updated_at: {datetime.now(timezone.utc).isoformat()}", text, flags=re.M)
    record_path.write_text(text, encoding="utf-8")
    return record_path


def _generate_release_notes_draft(record_path: Path) -> bool:
    if not record_path.exists():
        return False
    record = _parse_sprint_record(record_path)
    def _normalize_release_notes(value: object) -> str:
        text = str(value or "").strip()
        if text.lower() in {"not recorded yet", "none", "n/a"}:
            return ""
        return text

    internal_existing = _normalize_release_notes(record.get("internal_release_notes"))
    plain_existing = _normalize_release_notes(record.get("plain_english_release_notes"))
    if internal_existing and plain_existing:
        return False

    source_ideas = _source_idea_strings(_resolve_sprint_source_thoughts(record))
    proposed_work = [str(item).strip() for item in record.get("canonical_proposed_work") or record.get("proposed_work") or [] if str(item).strip()]
    completion_text = _extract_section_text(record_path.read_text(encoding="utf-8"), "Completion Notes")
    changes: dict[str, str] = {}
    if not internal_existing:
        internal_lines = [
            f"{record.get('title') or record.get('sprint_group_name') or 'Sprint'} was completed and is ready for review.",
            "",
            "Sprint Code:",
            str(record.get("sprint_code") or record.get("intended_sprint_code") or ""),
            "",
            "Source Ideas:",
            *([f"- {item}" for item in source_ideas] or ["- None recorded."]),
            "",
            "Proposed Work:",
            *([f"- {item}" for item in proposed_work] or ["- None recorded."]),
        ]
        if completion_text:
            internal_lines.extend(["", "Completion Notes:", completion_text])
        changes["internal_release_notes"] = "\n".join(line for line in internal_lines if line is not None).strip()
    if not plain_existing:
        plain_lines = [
            f"We finished {record.get('title') or record.get('sprint_group_name') or 'this sprint'}.",
            "",
            "What changed:",
            *([f"- {item}" for item in source_ideas[:3]] or ["- No source ideas were recorded."]),
        ]
        if completion_text:
            plain_lines.extend(["", "Review notes:", completion_text])
        changes["plain_english_release_notes"] = "\n".join(line for line in plain_lines if line is not None).strip()
    if not changes:
        return False
    _update_sprint_record_text(record_path, changes)
    return True


def _sprint_record_by_id(sprint_id: str) -> dict[str, object] | None:
    sprint_id = sprint_id.strip()
    for record in _sprint_records():
        if record.get("id") == sprint_id:
            return record
        proposal_id = str(record.get("proposal_id") or record.get("id") or "").strip()
        if proposal_id == sprint_id:
            return record
        path_stem = Path(str(record.get("path") or "")).stem
        if path_stem.startswith(sprint_id):
            return record
        if sprint_id and proposal_id.startswith(sprint_id):
            return record
    return None


def _sprint_record_by_code(sprint_code: str) -> dict[str, object] | None:
    sprint_code = sprint_code.strip().upper()
    records = [record for record in _sprint_records() if str(record.get("sprint_code") or "").strip().upper() == sprint_code]
    if not records:
        return None
    canonical = _sprint_duplicate_canonical_record(records)
    if canonical and len(records) > 1:
        warning = _sprint_duplicate_resolution_warning(records, canonical)
        canonical = {**canonical}
        canonical["duplicate_warning"] = warning
        canonical["duplicate_records"] = _sprint_duplicate_match_details(records)
        canonical["duplicate_canonical_path"] = canonical.get("path")
        canonical["duplicate_conflict"] = any(str(record.get("path") or "") != str(canonical.get("path") or "") for record in records)
        return canonical
    if records:
        record = {**records[0]}
        if len(records) > 1:
            record["duplicate_warning"] = _sprint_duplicate_resolution_warning(records, None)
            record["duplicate_records"] = _sprint_duplicate_match_details(records)
            record["duplicate_conflict"] = True
        return record
    return None


def _sprint_queue_dashboard_counts() -> dict[str, int]:
    records = _sprint_records()
    return {
        "proposed": sum(1 for record in records if record.get("status_key") == "proposed"),
        "approved": sum(1 for record in records if record.get("status_key") == "approved"),
        "active": sum(1 for record in records if record.get("status_key") == "active"),
        "completed": sum(1 for record in records if record.get("status_key") == "completed"),
        "staged": sum(1 for record in records if record.get("status_key") == "staged"),
        "shipped": sum(1 for record in records if record.get("status_key") == "shipped"),
    }


def _rescind_or_delete_sprint(record: dict[str, object], status: str, reason: str = "", performed_by: str = "") -> dict[str, object]:
    status = status.lower()
    if status not in {"rescinded", "deleted"}:
        raise ValueError(f"Unsupported archive status: {status}")

    restored_paths, warnings, restore_counts = _restore_source_ideas_for_record(record, restore_reason=status)
    record = {**record}
    record["restored_source_thought_paths"] = restored_paths
    record["restored_source_ideas_count"] = len(restored_paths)
    record["missing_source_ideas_count"] = len(warnings)
    record["restore_counts"] = restore_counts
    record["restore_warnings"] = warnings
    record["archive_reason"] = reason
    record["archived_by"] = performed_by or "system"
    record["archived_at"] = datetime.now(timezone.utc).isoformat()
    if status == "rescinded":
        record["rescinded_at"] = record["archived_at"]
    else:
        record["deleted_at"] = record["archived_at"]

    source_path = WORKLOG_ROOT / str(record["path"])
    _append_sprint_audit_note(
        source_path,
        [
            "## Archive Note",
            f"- action: {status}",
            f"- archived_at: {record['archived_at']}",
            f"- archived_by: {record['archived_by']}",
            f"- restored_source_ideas_count: {record['restored_source_ideas_count']}",
            f"- missing_source_ideas_count: {record['missing_source_ideas_count']}",
            f"- restore_counts: {json.dumps(restore_counts, sort_keys=True)}",
            f"- reason: {reason or 'none'}",
            *([f"- warning: {warning}" for warning in warnings] or []),
        ],
    )
    new_path = _archive_sprint_record(record, status)
    if not new_path:
        return record
    record["path"] = str(new_path.relative_to(WORKLOG_ROOT))
    record["status_key"] = status
    record["status"] = status.title()

    if record.get("handoff_path"):
        moved_handoff = _move_handoff_record(record, status)
        if moved_handoff:
            record["handoff_path"] = moved_handoff
    return record


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
    worklog_markers = [
        "worklog",
        "idea inventory",
        "sprint queue",
        "inbox",
        "proposed sprint group",
        "proposed sprint groups",
        "handoff",
        "dashboard",
        "active idea inventory",
    ]
    if any(marker in text for marker in worklog_markers):
        app_guess = "Worklog"
    app_labels = {
        "ims": "IMS",
        "dispatch": "Dispatch",
        "cy storage": "CY Storage",
        "core": "Core",
        "unity": "Unity",
        "parking": "Parking",
        "hiring": "Hiring",
    }
    for candidate, label in app_labels.items():
        if candidate in text and not app_guess:
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


def _sprint_group_name(app_name: str, thoughts: list[dict[str, str]]) -> str:
    keywords = " ".join(thought.get("raw_text", "") for thought in thoughts).lower()
    worklog_focus = app_name == "Worklog" and any(
        token in keywords
        for token in [
            "ui",
            "layout",
            "design",
            "copy",
            "dashboard",
            "idea inventory",
            "sprint queue",
            "inbox",
            "navigation",
            "menu",
            "selection",
            "date",
            "time",
            "workflow",
            "hand-off",
            "handoff",
        ]
    )
    if worklog_focus:
        if any(token in keywords for token in ["navigation", "menu", "inbox"]):
            focus = "Navigation Simplification"
        elif any(token in keywords for token in ["queue", "selection", "dashboard", "idea inventory"]):
            focus = "Idea Inventory UI Cleanup"
        else:
            focus = "Sprint Queue UX Cleanup"
    elif any(token in keywords for token in ["ui", "layout", "design", "copy", "dashboard"]):
        focus = "UI cleanup"
    elif any(token in keywords for token in ["import", "ingest", "capture", "webhook"]):
        focus = "intake flow"
    elif any(token in keywords for token in ["report", "summary", "log", "table"]):
        focus = "reporting"
    elif any(token in keywords for token in ["approval", "status", "workflow", "routing"]):
        focus = "workflow"
    elif any(token in keywords for token in ["bug", "error", "fail", "broken"]):
        focus = "bug fix"
    else:
        focus = "follow-up"
    return f"{app_name} {focus}".strip()


def _sprint_group_type(thoughts: list[dict[str, str]]) -> str:
    types = [thought.get("ai_inferred_type") or "thought" for thought in thoughts]
    if "feature" in types:
        return "Feature"
    if "bug" in types:
        return "Bug Fix"
    if "support" in types:
        return "Support"
    return "Mixed Follow-Up"


def _sprint_group_feasibility(thoughts: list[dict[str, str]]) -> str:
    if len(thoughts) <= 2:
        return "High"
    if len(thoughts) <= 4:
        return "Medium"
    return "Lower"


def _sprint_group_scope(thoughts: list[dict[str, str]]) -> str:
    if len(thoughts) <= 2:
        return "Small"
    if len(thoughts) <= 4:
        return "Medium"
    return "Large"


def _sprint_group_priority(thoughts: list[dict[str, str]]) -> str:
    types = [thought.get("ai_inferred_type") or "thought" for thought in thoughts]
    if "bug" in types:
        return "High"
    if "feature" in types:
        return "Medium"
    if "support" in types:
        return "Medium"
    return "Low"


def _build_codex_prompt(app_name: str, sprint_name: str, thoughts: list[dict[str, str]], sprint_code: str = "", purpose: str = "") -> str:
    canonical_thoughts = _canonicalize_source_thoughts([thought for thought in thoughts if isinstance(thought, dict)])
    source_titles = ", ".join(_source_idea_strings(canonical_thoughts)[:5])
    purpose = purpose or (thoughts[0].get("purpose") if thoughts else "Turn raw ideas into a focused sprint.")
    return (
        f"Start a focused implementation conversation for {app_name}. "
        f"Work on the sprint group '{sprint_name}'. "
        f"Sprint Code: {sprint_code or 'TBD'}. "
        f"Purpose: {purpose}. "
        "Completion Requirement: Mark work Completed when implementation is finished but not yet deployed. Mark it Staged when deployed to DEV or staging and ready for validation. Mark it Shipped when deployed to production or live. Update the matching Sprint Queue record by Sprint Code and do not leave the sprint status stale. "
        f"Source ideas: {source_titles}. "
        "Keep the scope small, preserve existing behavior, and return a concise plan before editing files."
    )


def _sprint_handoff_payload(record: dict[str, object], thoughts: list[dict[str, str]] | None = None) -> dict[str, object]:
    canonical_thoughts = _canonicalize_source_thoughts([thought for thought in (thoughts or []) if isinstance(thought, dict)])
    if not canonical_thoughts:
        canonical_thoughts = _canonicalize_source_thoughts(_resolve_sprint_source_thoughts(record))
    source_idea_summaries = _source_idea_strings(canonical_thoughts)
    if not source_idea_summaries:
        source_idea_summaries = [str(item).strip() for item in record.get("canonical_source_ideas") or record.get("source_idea_summaries") or record.get("source_ideas") or [] if str(item).strip()]
    proposed_work = [str(item).strip() for item in record.get("canonical_proposed_work") or record.get("proposed_work") or [] if str(item).strip()]
    if not proposed_work:
        proposed_work = list(source_idea_summaries)
    purpose = str(record.get("purpose") or "").strip() or f"Turn {str(record.get('app_product') or 'Worklog')} raw ideas into a focused sprint-sized implementation conversation."
    sprint_code = str(record.get("intended_sprint_code") or record.get("sprint_code") or (canonical_thoughts[0].get("sprint_code") if canonical_thoughts else "") or "TBD").strip()
    app_product = str(record.get("app_product") or "Worklog")
    sprint_name = str(record.get("sprint_group_name") or record.get("title") or "Sprint")
    recommended_first_step = str(record.get("recommended_first_step") or "").strip() or (
        canonical_thoughts[0].get("normalized_summary")
        if canonical_thoughts and canonical_thoughts[0].get("normalized_summary")
        else "Open the source ideas, confirm the smallest common implementation slice, and outline the first chat response."
    )
    scope = str(record.get("scope") or "").strip() or _sprint_group_scope(canonical_thoughts)
    starting_prompt = str(record.get("starting_prompt") or "").strip() or _build_codex_prompt(app_product, sprint_name, canonical_thoughts, sprint_code, purpose)
    return {
        "canonical_thoughts": canonical_thoughts,
        "source_idea_summaries": source_idea_summaries,
        "proposed_work": proposed_work,
        "purpose": purpose,
        "sprint_code": sprint_code,
        "app_product": app_product,
        "sprint_name": sprint_name,
        "recommended_first_step": recommended_first_step,
        "scope": scope,
        "starting_prompt": starting_prompt,
    }


def _build_handoff_markdown_from_record(record: dict[str, object], thoughts: list[dict[str, str]] | None = None) -> str:
    payload = _sprint_handoff_payload(record, thoughts)
    source_ideas = [f"- {item}" for item in payload["source_idea_summaries"]]
    proposed_work = [f"- {item}" for item in payload["proposed_work"]]
    return "\n".join(
        [
            f"# Sprint Handoff: {payload['sprint_name']}",
            "",
            "## Sprint Code",
            payload["sprint_code"],
            "",
            f"## App/Product",
            payload["app_product"],
            "",
            "## Purpose",
            payload["purpose"],
            "",
            "## Source Ideas",
            *(source_ideas or ["- No handoff content found. Regenerate handoff."]),
            "",
            "## Proposed Work",
            *(proposed_work or ["- Triage raw ideas into a focused implementation plan."]),
            "",
            "## Suggested Scope",
            payload["scope"],
            "",
            "## Recommended First Step",
            payload["recommended_first_step"],
            "",
            "## Completion Requirement",
            f"When implementation is finished but not deployed, mark the sprint Completed. When deployed to DEV or staging and ready for validation, mark the sprint Staged. When deployed to production or live, mark the sprint Shipped. Update Worklog using Sprint Code {payload['sprint_code']}.",
            "",
            "## Codex/ChatGPT Starting Prompt",
            payload["starting_prompt"],
            "",
        ]
    )


def _preview_thought_items(items: list[dict[str, str]]) -> dict[str, object]:
    preview = _digest_groups_from_items(items)
    preview["source_thought_ids"] = [_thought_item_fingerprint(item) for item in items]
    preview["source_thought_paths"] = [item.get("path") for item in items]
    return preview


def _proposal_from_digest_group(group: dict[str, object]) -> dict[str, object]:
    thoughts = _canonicalize_source_thoughts([thought for thought in group.get("thoughts") or [] if isinstance(thought, dict)])
    intended_sprint_code = str(
        group.get("intended_sprint_code")
        or group.get("sprint_code")
        or _generate_sprint_code(str(group.get("app_product") or "Other"))
    )
    source_idea_summaries = _source_idea_strings(thoughts)
    source_thought_paths = [thought.get("path") for thought in thoughts if thought.get("path")]
    source_thought_ids = [_thought_item_fingerprint(thought) for thought in thoughts if thought.get("path")]
    source_created_ats = [thought.get("created_at") or "" for thought in thoughts if thought.get("path")]
    source_request_paths = [str(thought.get("source_request_path") or "").strip() for thought in thoughts if str(thought.get("source_request_path") or "").strip()]
    source_request_ids = [str(thought.get("source_request_id") or thought.get("source_request_path") or "").strip() for thought in thoughts if str(thought.get("source_request_id") or thought.get("source_request_path") or "").strip()]
    return {
        **group,
        "proposal_id": group.get("proposal_id") or _generate_proposal_id(),
        "intended_sprint_code": intended_sprint_code,
        "sprint_code": intended_sprint_code,
        "status": "proposed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source_thought_paths": source_thought_paths,
        "source_thought_ids": source_thought_ids,
        "source_created_ats": source_created_ats,
        "source_request_paths": source_request_paths,
        "source_request_ids": source_request_ids,
        "source_idea_summaries": source_idea_summaries,
        "proposed_work": _source_idea_strings(thoughts) or group.get("proposed_work") or source_idea_summaries,
        "canonical_source_ideas": source_idea_summaries,
        "canonical_proposed_work": _source_idea_strings(thoughts) or group.get("proposed_work") or source_idea_summaries,
        "starting_prompt": str(group.get("starting_prompt") or ""),
        "handoff_md": _build_handoff_markdown_from_record(
            {
                **group,
                "intended_sprint_code": intended_sprint_code,
                "canonical_source_ideas": source_idea_summaries,
                "canonical_proposed_work": _source_idea_strings(thoughts) or group.get("proposed_work") or source_idea_summaries,
                "starting_prompt": str(group.get("starting_prompt") or ""),
            },
            thoughts,
        ),
    }


def _create_proposed_sprints_from_preview(preview: dict[str, object], mode: str = "suggested") -> list[dict[str, object]]:
    groups = [group for group in preview.get("sprint_groups") or [] if isinstance(group, dict)]
    if mode == "combine_all":
        all_thoughts = []
        for group in groups:
            for thought in group.get("thoughts") or []:
                if isinstance(thought, dict):
                    all_thoughts.append(thought)
        if not all_thoughts:
            all_thoughts = [thought for thought in _thought_box_items(digested_only=False) if isinstance(thought, dict)]
        all_thoughts = _canonicalize_source_thoughts(all_thoughts)
        if not all_thoughts:
            return []
        app_product = preview.get("combined_app_product") or max(
            {thought.get("ai_inferred_app") or "Other" for thought in all_thoughts},
            key=lambda app_name: sum(1 for thought in all_thoughts if (thought.get("ai_inferred_app") or "Other") == app_name),
        )
        combined_group = {
            "app_product": app_product,
            "sprint_group_name": preview.get("combined_sprint_group_name") or _sprint_group_name(app_product, all_thoughts),
            "ideas_included": len(all_thoughts),
            "proposed_type": _sprint_group_type(all_thoughts),
            "feasibility": _sprint_group_feasibility(all_thoughts),
            "suggested_priority": _sprint_group_priority(all_thoughts),
            "recommended_first_step": all_thoughts[0].get("normalized_summary") if all_thoughts else "Review the source ideas and choose the smallest focused implementation slice.",
            "source_thoughts": [thought.get("path") for thought in all_thoughts if thought.get("path")],
            "scope": _sprint_group_scope(all_thoughts),
            "purpose": "Combine the selected Worklog ideas into one reviewed sprint proposal." if app_product == "Worklog" else f"Combine the selected {app_product} ideas into one reviewed sprint proposal.",
            "thoughts": all_thoughts,
        }
        groups = [combined_group]
    created = []
    for group in groups:
        summary_signature = _sprint_summary_signature_from_items([thought for thought in group.get("thoughts") or [] if isinstance(thought, dict)])
        existing = next(
            (
                record
                for record in _sprint_records()
                if record.get("status_key") not in {"rejected", "rescinded", "deleted"}
                and _sprint_summary_signature_from_record(record) == summary_signature
                and summary_signature
            ),
            None,
        )
        if existing:
            created.append({**existing, "_existing_duplicate": True})
            continue
        proposal = _proposal_from_digest_group(group)
        record_path = _write_proposed_sprint_record(proposal)
        proposal["path"] = str(record_path.relative_to(WORKLOG_ROOT))
        moved_thoughts = []
        for thought in group.get("thoughts") or []:
            if not isinstance(thought, dict) or not thought.get("path"):
                continue
            source_file = WORKLOG_ROOT / str(thought["path"])
            if source_file.exists():
                destination = _move_thought(source_file, _thought_proposed_dir())
                moved_thoughts.append(str(destination.relative_to(WORKLOG_ROOT)))
        proposal["proposed_source_thoughts"] = moved_thoughts
        proposal["digested_source_thoughts"] = []
        _update_sprint_record(record_path, "proposed")
        created.append(proposal)
    return created


def _group_thoughts_for_sprints(items: list[dict[str, str]]) -> dict[str, object]:
    if not items:
        return {
            "plain_summary": "No active raw ideas to digest.",
            "active_items": [],
            "app_groups": [],
            "sprint_groups": [],
            "approved_handoffs": [],
            "recommended_codex_prompt": "No active raw ideas available.",
        }

    active_items = []
    for item in items:
        raw = item.get("raw_text", "")
        inferred = _infer_thought(raw)
        inferred_app = inferred["ai_inferred_app"] or "Other"
        if inferred_app not in APP_ORDER:
            inferred_app = "Other"
        active_items.append({**item, **inferred, "ai_inferred_app": inferred_app, "normalized_summary": _normalize_idea_summary(raw, item.get("title", ""), item.get("path", ""))})
    active_items = _canonicalize_source_thoughts(active_items)

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in active_items:
        grouped[item["ai_inferred_app"] or "Other"].append(item)

    app_groups = []
    sprint_groups = []
    reserved_codes = set(_existing_sprint_codes())
    for app_name in APP_ORDER:
        thoughts = grouped.get(app_name, [])
        if not thoughts:
            continue
        app_groups.append(
            {
                "app_product": app_name,
                "thought_count": len(thoughts),
                "thought_titles": _source_idea_strings(thoughts[:5]),
            }
        )
        by_cluster: dict[str, list[dict[str, str]]] = defaultdict(list)
        for thought in thoughts:
            cluster_key = thought.get("ai_inferred_type") or "thought"
            bucket = "workflow"
            raw = thought.get("raw_text", "").lower()
            if any(token in raw for token in ["ui", "layout", "design", "copy", "dashboard"]):
                bucket = "ui"
            elif any(token in raw for token in ["import", "ingest", "capture", "webhook"]):
                bucket = "intake"
            elif any(token in raw for token in ["report", "summary", "log", "table"]):
                bucket = "reporting"
            elif any(token in raw for token in ["approval", "status", "workflow", "routing"]):
                bucket = "workflow"
            elif cluster_key == "bug":
                bucket = "bug"
            by_cluster[bucket].append(thought)

        for cluster_name, cluster_thoughts in by_cluster.items():
            sprint_name = _sprint_group_name(app_name, cluster_thoughts)
            sprint_code = _generate_sprint_code(app_name, reserved_codes)
            reserved_codes.add(sprint_code)
            proposed_type = _sprint_group_type(cluster_thoughts)
            feasibility = _sprint_group_feasibility(cluster_thoughts)
            priority = _sprint_group_priority(cluster_thoughts)
            first_step = (
                cluster_thoughts[0].get("normalized_summary")
                if cluster_thoughts and cluster_thoughts[0].get("normalized_summary")
                else "Review the source ideas and choose the smallest focused implementation slice."
            )
            purpose = (
                "Clean up the Worklog Idea Inventory and navigation experience by improving row selection, date formatting, and menu simplicity."
                if app_name == "Worklog"
                else f"Turn {app_name} ideas into a focused {cluster_name} sprint."
            )
            group = {
                "app_product": app_name,
                "sprint_code": sprint_code,
                "intended_sprint_code": sprint_code,
                "sprint_group_name": sprint_name,
                "ideas_included": len(cluster_thoughts),
                "proposed_type": proposed_type,
                "feasibility": feasibility,
                "suggested_priority": priority,
                "recommended_first_step": first_step,
            "source_thoughts": [thought["path"] for thought in _canonicalize_source_thoughts(cluster_thoughts)],
            "proposed_work": _source_idea_strings(cluster_thoughts),
                "scope": _sprint_group_scope(cluster_thoughts),
                "purpose": purpose,
                "starting_prompt": "",
                "thoughts": cluster_thoughts,
            }
            group["starting_prompt"] = _build_codex_prompt(app_name, sprint_name, cluster_thoughts, sprint_code, group["purpose"])
            sprint_groups.append(group)

    if not sprint_groups:
        thought = active_items[0]
        sprint_name = _sprint_group_name(thought["ai_inferred_app"], [thought])
        sprint_code = _generate_sprint_code(thought["ai_inferred_app"], reserved_codes)
        reserved_codes.add(sprint_code)
        sprint_groups.append(
            {
                "app_product": thought["ai_inferred_app"],
                "sprint_code": sprint_code,
                "intended_sprint_code": sprint_code,
                "sprint_group_name": sprint_name,
                "ideas_included": 1,
                "proposed_type": _sprint_group_type([thought]),
                "feasibility": "High",
                "suggested_priority": _sprint_group_priority([thought]),
                "recommended_first_step": thought.get("normalized_summary") or "Review the source idea.",
                "source_thoughts": [thought["path"]],
                "proposed_work": _source_idea_strings([thought]) if thought.get("raw_text_full") else [],
                "scope": "Small",
                "purpose": "Clean up the Worklog Idea Inventory and navigation experience by improving row selection, date formatting, and menu simplicity."
                if thought["ai_inferred_app"] == "Worklog"
                else f"Turn {thought['ai_inferred_app']} ideas into a focused sprint.",
                "starting_prompt": _build_codex_prompt(
                    thought["ai_inferred_app"],
                    sprint_name,
                    [thought],
                    sprint_code,
                    "Clean up the Worklog Idea Inventory and navigation experience by improving row selection, date formatting, and menu simplicity."
                    if thought["ai_inferred_app"] == "Worklog"
                    else f"Turn {thought['ai_inferred_app']} ideas into a focused sprint.",
                ),
                "thoughts": [thought],
            }
        )

    return {
        "plain_summary": f"{len(active_items)} active raw thought item(s) grouped into {len(app_groups)} app bucket(s) and {len(sprint_groups)} sprint group(s).",
        "active_items": active_items,
        "app_groups": app_groups,
        "sprint_groups": sprint_groups,
        "source_thoughts": [item.get("path") for item in active_items],
        "source_idea_summaries": [item.get("normalized_summary") or item.get("display_snippet") or item.get("title") for item in active_items],
        "source_thought_paths": [item.get("path") for item in active_items],
        "source_thought_ids": [_thought_item_fingerprint(item) for item in active_items],
        "recommended_codex_prompt": "Create a focused implementation conversation from the sprint group table. Keep each group small enough to start a new chat cleanly.",
    }


def _proposal_view_from_group(group: dict[str, object]) -> dict[str, object]:
    return {
        "proposal_id": group.get("proposal_id") or "",
        "intended_sprint_code": group.get("intended_sprint_code") or group.get("sprint_code") or "",
        "sprint_group_name": group.get("sprint_group_name") or "",
        "app_product": group.get("app_product") or "Other",
        "ideas_included": len(group.get("source_thought_ids") or group.get("source_thought_paths") or []),
        "scope": group.get("scope") or "Small",
        "status": group.get("status") or "proposed",
        "sprint_code": group.get("sprint_code") or "",
        "source_thought_ids": group.get("source_thought_ids") or [],
        "source_thought_paths": group.get("source_thought_paths") or [],
        "source_ideas": group.get("source_ideas") or [],
        "proposed_work": group.get("proposed_work") or [],
        "recommended_first_step": group.get("recommended_first_step") or "",
        "handoff_md": group.get("handoff_md") or "",
        "path": group.get("path") or "",
        "purpose": group.get("purpose") or "",
    }


def _digest_preview(items: list[dict[str, str]]) -> dict[str, object]:
    return _group_thoughts_for_sprints(items)


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
        "recent_worklog_pages": _recent_worklog_pages(),
        "content_root": str(WORKLOG_ROOT),
        "now_utc": None,
        "is_authenticated": _is_authenticated(),
        "is_super_admin": _is_super_admin(),
        "display_timestamp": _format_pacific_timestamp,
    }


@app.route("/")
@_require_worklog_session
def dashboard():
    app_cards = [_parse_active_work_file(item["path"], item["title"]) for item in ACTIVE_WORK_FILES]
    app_cards.append(
        {
            "slug": "other",
            "title": "Other",
            "path": "",
            "has_active_sprint": False,
            "current_sprint_name": "",
            "current_sprint_percent": "",
            "current_sprint_status": "",
            "current_sprint_notes": "",
            "last_sprint_name": "Not recorded",
            "last_sprint_completed": "",
            "last_sprint_outcome": "No completion note recorded.",
            "next_suggested_sprint_name": "Not set",
            "next_suggested_sprint_first_step": "No next action recorded.",
            "next_suggested_sprint_why": "",
            "blockers_count": 0,
            "sprint_counts": {"proposed": 0, "approved": 0, "active": 0, "done": 0, "staged": 0, "shipped": 0},
            "inbox_items": [],
        }
    )
    counts = _dashboard_counts()
    inbox_items = _recent_inbox_items()
    update_shipments = _assistant_update_shipments()
    sprint_counts = _sprint_counts_by_app()

    return render_template(
        "dashboard.html",
        counts=counts,
        app_cards=app_cards,
        sprint_counts=sprint_counts,
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
@app.route("/requests", methods=["GET", "POST"])
@_require_worklog_session
def intake():
    if request.method == "POST":
        action = (request.form.get("action") or "create").strip().lower()
        if action == "convert":
            request_path = request.form.get("request_path") or ""
            if not request_path:
                return {"ok": False, "error": "request_path is required"}, 400
            converted_path = _convert_user_request_to_idea(_resolve_worklog_path(request_path))
            return redirect(url_for("view_file", relative_path=str(converted_path.relative_to(WORKLOG_ROOT))))
        created_path = _create_user_request_from_form(request.form)
        return redirect(url_for("view_file", relative_path=str(created_path.relative_to(WORKLOG_ROOT))))

    intake_counts = _dashboard_intake_counts()
    intake_items = _user_requests_items()[:8]
    plain_mode = _intake_plain_mode_enabled()
    return render_template(
        "intake.html",
        intake_counts=intake_counts,
        intake_items=intake_items,
        plain_mode=plain_mode,
        request_status_options=["New", "Reviewed", "Converted", "Closed"],
        request_source_types=["Customer", "Employee", "Vendor", "Internal", "Unknown"],
    )


@app.route("/requests/<path:request_id>", methods=["GET"])
@_require_worklog_session
def request_detail(request_id: str):
    record = _request_record_by_id(request_id)
    if not record:
        abort(404)
    notifications = _notifications_for_request(record["request_id"])
    idea = _parse_thought_file(WORKLOG_ROOT / record["idea_path"]) if record.get("idea_path") and (WORKLOG_ROOT / record["idea_path"]).exists() else None
    return render_template(
        "request_detail.html",
        title=record["request_title"],
        request_record=record,
        related_idea=idea,
        notifications=notifications,
    )


@app.route("/notifications", methods=["GET"])
@_require_worklog_session
def notifications_preview():
    return render_template(
        "notifications.html",
        title="Notification Preview",
        notifications=_notification_items(),
        request_count=len(_user_requests_items()),
    )


@app.route("/assistant")
@_require_worklog_session
def assistant():
    conversation = _thought_box_items(digested_only=False)[:12]
    digest_preview = None
    if request.args.get("digest_preview") == "1":
        digest_preview = _preview_thought_items(_thought_box_items(digested_only=False))
    return render_template(
        "assistant.html",
        conversation=conversation,
        digest_preview=digest_preview,
        update_shipments=_assistant_update_shipments(),
        openai_enabled=_openai_available(),
        idea_inventory_count=len(_thought_box_items(digested_only=False)),
    )


@app.route("/assistant/thought/<path:relative_path>", methods=["GET", "POST"])
@_require_worklog_session
def thought_detail(relative_path: str):
    path = _resolve_worklog_path(relative_path)
    if not str(path).startswith(str(THOUGHT_BOX_DIR)):
        abort(404)
    if request.method == "POST":
        updates = {
            "title": (request.form.get("title") or "").strip(),
            "ai_inferred_app": (request.form.get("ai_inferred_app") or "").strip() or None,
            "ai_inferred_type": (request.form.get("ai_inferred_type") or "").strip() or None,
            "raw_text": (request.form.get("raw_text") or "").strip(),
            "ai_summary": (request.form.get("ai_summary") or "").strip() or None,
        }
        _update_thought_file(path, {key: value for key, value in updates.items() if value is not None})
        flash("Idea details updated.", "success")
        return redirect(url_for("thought_detail", relative_path=relative_path))
    item = _parse_thought_file(path)
    return render_template("thought_detail.html", thought=item)


@app.route("/sprints", methods=["GET"])
@_require_worklog_session
def sprints():
    status = (request.args.get("status") or "all").strip().lower()
    if status not in {"all", "proposed", "rescinded", "deleted", "approved", "active", "completed", "staged", "shipped", "done", "reconciled"}:
        status = "all"
    app_slug = _normalize_app_filter(request.args.get("app"))
    records = _filter_sprint_records(_sprint_records(), status, app_slug)
    return render_template(
        "sprints.html",
        title="Sprint Queue",
        records=records,
        status_filter=status,
        app_filter=app_slug,
        status_options=[
            {"value": "all", "label": "All"},
            {"value": "proposed", "label": "Proposed"},
            {"value": "rescinded", "label": "Rescinded"},
            {"value": "deleted", "label": "Deleted"},
            {"value": "approved", "label": "Approved"},
            {"value": "active", "label": "Active"},
            {"value": "completed", "label": "Completed"},
            {"value": "staged", "label": "Staged"},
            {"value": "shipped", "label": "Shipped"},
            {"value": "done", "label": "Done"},
            {"value": "reconciled", "label": "Reconciled"},
        ],
        proposed_sprints=[record for record in records if record.get("status_key") == "proposed"],
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


@app.route("/sprints/<sprint_id>", methods=["GET", "POST"])
@_require_worklog_session
def sprint_detail(sprint_id: str):
    record = _sprint_record_by_id(sprint_id)
    if not record:
        abort(404)
    if request.method == "POST":
        action = (request.form.get("action") or "").strip().lower()
        if action != "update_release_notes":
            abort(400)
        notes = {
            "internal_release_notes": (request.form.get("internal_release_notes") or "").strip(),
            "plain_english_release_notes": (request.form.get("plain_english_release_notes") or "").strip(),
        }
        record_path = WORKLOG_ROOT / str(record["path"])
        _update_sprint_record_text(record_path, notes)
        flash("Release notes updated.", "success")
        updated_record = _sprint_record_by_id(sprint_id) or record
        return render_template(
            "sprint_detail.html",
            title=updated_record["title"],
            record=updated_record,
        )
    return render_template(
        "sprint_detail.html",
        title=record["title"],
        record=record,
    )


@app.route("/sprints/<sprint_id>/action", methods=["POST"])
@_require_worklog_session
def sprint_action(sprint_id: str):
    action = (request.form.get("action") or "").strip().lower()
    record = _sprint_record_by_id(sprint_id)
    if not record:
        abort(404)
    record_path = WORKLOG_ROOT / str(record["path"])
    if action == "start":
        new_path = _update_sprint_record(record_path, "active")
    elif action == "complete":
        should_flash_release_notes = not str(record.get("internal_release_notes") or "").strip() or not str(record.get("plain_english_release_notes") or "").strip()
        new_path = _update_sprint_record(record_path, "completed")
        if should_flash_release_notes:
            flash("Draft release notes generated. Please review before shipping.", "success")
    elif action == "stage":
        new_path = _update_sprint_record(record_path, "staged")
    elif action == "ship":
        new_path = _update_sprint_record(record_path, "shipped")
    elif action in {"done", "mark_done"}:
        new_path = _mark_sprint_done(record, performed_by=str(session.get(WORKLOG_SESSION_KEY, {}).get("username") or session.get(WORKLOG_SESSION_KEY, {}).get("email") or "ui"))
        return redirect(url_for("sprints", status="done"))
    elif action == "regenerate_handoff":
        regenerated, handoff_path, sprint_path = _regenerate_sprint_handoff_record(record)
        new_path = sprint_path
    elif action == "approve":
        if record.get("status_key") == "approved":
            return redirect(url_for("sprint_detail", sprint_id=record["id"]))
        if record.get("status_key") != "proposed":
            abort(400)
        approved_record = _approve_proposed_sprint_record(record)
        return redirect(url_for("sprint_detail", sprint_id=approved_record["id"]))
    elif action == "reject":
        if record.get("status_key") != "proposed":
            abort(400)
        _reject_proposed_sprint_record(record)
        return redirect(url_for("sprints", status="proposed"))
    elif action in {"rescind", "delete"}:
        confirm = (request.form.get("confirm") or "").strip().lower()
        expected = "rescind this sprint and return its ideas to inventory?" if action == "rescind" else "delete this sprint record and return its ideas to inventory?"
        if confirm != expected:
            return {"ok": False, "error": "Confirmation text did not match."}, 400
        performed_by = str(session.get(WORKLOG_SESSION_KEY, {}).get("username") or session.get(WORKLOG_SESSION_KEY, {}).get("email") or "system")
        reason = (request.form.get("reason") or "").strip()
        archived = _rescind_or_delete_sprint(record, "rescinded" if action == "rescind" else "deleted", reason=reason, performed_by=performed_by)
        active_inventory_count_after = len(_thought_box_items(digested_only=False))
        app.logger.info(
            "sprint %s %s restored_count=%s already_active_count=%s recreated_count=%s missing_count=%s restored_paths=%s active_inventory_count_after=%s",
            archived.get("sprint_code") or archived.get("id") or sprint_id,
            action,
            archived.get("restore_counts", {}).get("restored", 0),
            archived.get("restore_counts", {}).get("already_active", 0),
            archived.get("restore_counts", {}).get("recreated", 0),
            archived.get("restore_counts", {}).get("missing", 0),
            archived.get("restored_source_thought_paths", []),
            active_inventory_count_after,
        )
        restored_count = int(archived.get("restore_counts", {}).get("restored", 0)) + int(archived.get("restore_counts", {}).get("already_active", 0)) + int(archived.get("restore_counts", {}).get("recreated", 0))
        if restored_count:
            flash(
                f"Restored {restored_count} ideas to Idea Inventory.",
                "success",
            )
        else:
            warning_text = "No ideas were restored."
            missing_count = int(archived.get("restore_counts", {}).get("missing", 0))
            if missing_count:
                warning_text = f"No ideas were restored. {missing_count} source ideas were missing or unavailable."
            flash(warning_text, "warning")
        return redirect(url_for("sprints", status=archived["status_key"]))
    else:
        abort(400)
    return redirect(url_for("sprint_detail", sprint_id=sprint_id))


@app.route("/sprints/code/<sprint_code>", methods=["GET"])
@_require_worklog_session
def sprint_detail_by_code(sprint_code: str):
    record = _sprint_record_by_code(sprint_code)
    if not record:
        abort(404)
    return redirect(url_for("sprint_detail", sprint_id=record["id"]))


@app.route("/sprints/code/<sprint_code>/action", methods=["POST"])
@_require_worklog_session
def sprint_action_by_code(sprint_code: str):
    record = _sprint_record_by_code(sprint_code)
    if not record:
        abort(404)
    if record.get("duplicate_conflict"):
        return {"ok": False, "error": "Duplicate sprint code conflict. Resolve duplicates before mutating by code.", "matches": record.get("duplicate_records", [])}, 409
    confirmation = (request.form.get("confirm") or "").strip().lower()
    if confirmation != "yes":
        return {"ok": False, "error": "Confirmation required to update sprint status by code."}, 400
    action = (request.form.get("action") or "").strip().lower()
    record_path = WORKLOG_ROOT / str(record["path"])
    if action == "start":
        record_path = _update_sprint_record(record_path, "active")
    elif action == "complete":
        should_flash_release_notes = not str(record.get("internal_release_notes") or "").strip() or not str(record.get("plain_english_release_notes") or "").strip()
        record_path = _update_sprint_record(record_path, "completed")
        if should_flash_release_notes:
            flash("Draft release notes generated. Please review before shipping.", "success")
    elif action == "stage":
        record_path = _update_sprint_record(record_path, "staged")
    elif action == "ship":
        record_path = _update_sprint_record(record_path, "shipped")
    elif action in {"done", "mark_done"}:
        record_path = _mark_sprint_done(record, performed_by=str(session.get(WORKLOG_SESSION_KEY, {}).get("username") or session.get(WORKLOG_SESSION_KEY, {}).get("email") or "ui"))
        return redirect(url_for("sprints", status="done"))
    elif action == "regenerate_handoff":
        regenerated, handoff_path, sprint_path = _regenerate_sprint_handoff_record(record)
        record_path = sprint_path
    else:
        abort(400)
    notes = (request.form.get("completion_notes") or "").strip()
    if notes:
        _append_sprint_completion_notes(record_path, notes)
    return redirect(url_for("sprint_detail", sprint_id=record["id"]))


@app.route("/sprints/regenerate-handoffs", methods=["POST"])
@_require_worklog_session
def regenerate_all_sprint_handoffs():
    confirmation = (request.form.get("confirm") or "").strip().lower()
    if confirmation != "yes":
        return {"ok": False, "error": "Confirmation required to regenerate all sprint handoffs."}, 400
    regenerated = []
    for record in _sprint_records():
        if record.get("status_key") != "approved":
            continue
        rebuilt, handoff_path, sprint_path = _regenerate_sprint_handoff_record(record)
        regenerated.append({
            "sprint_id": rebuilt["id"],
            "sprint_code": rebuilt["sprint_code"],
            "handoff_path": str(handoff_path.relative_to(WORKLOG_ROOT)),
            "sprint_path": str(sprint_path.relative_to(WORKLOG_ROOT)),
        })
    return {
        "ok": True,
        "regenerated": regenerated,
        "sprint_queue_url": url_for("sprints"),
    }


@app.route("/validation-sessions", methods=["GET"])
@_require_worklog_session
def validation_sessions():
    records = _validation_session_records()
    return render_template(
        "validation_sessions.html",
        title="Validation Sessions",
        records=records,
    )


@app.route("/validation-sessions/<session_slug>", methods=["GET", "POST"])
@_require_worklog_session
def validation_session_detail(session_slug: str):
    record_path, record = _validation_session_record_by_slug(session_slug)
    if not record_path or not record:
        abort(404)
    def render_detail(
        current_record: dict[str, object],
        *,
        handoff_path_value: str | None = None,
        handoff_markdown_value: str | None = None,
    ):
        items = list(current_record.get("items") or [])
        sections: list[dict[str, object]] = []
        seen_sections: list[str] = []
        for item in items:
            section = str(item.get("section") or "Section").strip() or "Section"
            if section not in seen_sections:
                seen_sections.append(section)
                sections.append({"section": section, "items": []})
            for bucket in sections:
                if bucket["section"] == section:
                    bucket["items"].append(item)
                    break
        resolved_handoff_path = (
            handoff_path_value
            if handoff_path_value is not None
            else str(current_record.get("handoff_path") or "").strip()
        )
        if handoff_markdown_value is not None:
            resolved_handoff_markdown = handoff_markdown_value
        else:
            resolved_handoff_markdown = ""
            if resolved_handoff_path:
                handoff_file = WORKLOG_ROOT / resolved_handoff_path
                if handoff_file.exists():
                    resolved_handoff_markdown = handoff_file.read_text(encoding="utf-8")
        return render_template(
            "validation_session_detail.html",
            title=current_record.get("title") or "Validation Session",
            record=current_record,
            sections=sections,
            status_counts=validation_session_store.session_status_counts(current_record),
            handoff_path=resolved_handoff_path,
            handoff_markdown=resolved_handoff_markdown,
            ai_prompt=validation_session_store.generate_ai_prompt(current_record, resolved_handoff_markdown)
            if resolved_handoff_markdown
            else "",
        )

    if request.method == "POST":
        action = _validation_session_request_value("action").lower()
        if action == "save_item":
            item_id = _validation_session_request_value("item_id")
            if not item_id:
                abort(400)
            record = _validation_session_apply_form(record, request.form, item_id=item_id)
            validation_session_store.write_session(record_path, record)
            flash("Validation item saved.", "success")
            return redirect(url_for("validation_session_detail", session_slug=record.get("slug") or session_slug))
        if action == "save_all":
            record = _validation_session_apply_form(record, request.form)
            validation_session_store.write_session(record_path, record)
            flash("Validation session saved.", "success")
            return redirect(url_for("validation_session_detail", session_slug=record.get("slug") or session_slug))
        if action == "set_status":
            target_status = _validation_session_request_value("target_status")
            if target_status not in validation_session_store.ALLOWED_SESSION_STATUSES:
                abort(400)
            record["status"] = target_status
            if target_status == "completed":
                record = validation_session_store.complete_session(record)
            else:
                record["updated_at"] = validation_session_store.now_iso()
                if target_status == "blocked":
                    record["blocked_at"] = validation_session_store.now_iso()
            record = _validation_session_apply_form(record, request.form)
            validation_session_store.write_session(record_path, record)
            flash(f"Validation session marked {target_status.replace('_', ' ')}.", "success")
            return redirect(url_for("validation_session_detail", session_slug=record.get("slug") or session_slug))
        if action == "generate_handoff":
            record = _validation_session_apply_form(record, request.form)
            include_notes = _validation_session_form_flag(request.form, "include_notes", True)
            include_passed = _validation_session_form_flag(request.form, "include_passed", True)
            include_pending = _validation_session_form_flag(request.form, "include_pending", True)
            include_blocked = _validation_session_form_flag(request.form, "include_blocked", True)
            include_na = _validation_session_form_flag(request.form, "include_na", True)
            include_finding_summaries = _validation_session_form_flag(request.form, "include_finding_summaries", True)
            handoff_dir = validation_session_store.handoff_dir(WORKLOG_ROOT)
            handoff_dir.mkdir(parents=True, exist_ok=True)
            output = handoff_dir / f"{record.get('slug') or session_slug}.md"
            try:
                handoff_md = validation_session_store.generate_handoff_markdown(
                    record,
                    session_path_value=record_path,
                    include_notes=include_notes,
                    include_passed=include_passed,
                    include_pending=include_pending,
                    include_blocked=include_blocked,
                    include_na=include_na,
                    include_finding_summaries=include_finding_summaries,
                )
                output.write_text(handoff_md, encoding="utf-8")
                written_handoff = output.read_text(encoding="utf-8")
                if written_handoff != handoff_md:
                    raise IOError("Validation handoff readback did not match written content.")
                record["handoff_path"] = str(output.relative_to(WORKLOG_ROOT))
                record["updated_at"] = validation_session_store.now_iso()
                validation_session_store.write_session(record_path, record)
                record_path, persisted_record = _validation_session_record_by_slug(session_slug)
                if persisted_record:
                    record = persisted_record
                if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.args.get("format") == "json":
                    prompt_text = validation_session_store.generate_ai_prompt(record, written_handoff)
                    return jsonify(
                        {
                            "ok": True,
                            "handoff_path": record["handoff_path"],
                            "handoff_markdown": written_handoff,
                            "ai_prompt": prompt_text,
                            "include_notes": include_notes,
                            "include_passed": include_passed,
                            "include_pending": include_pending,
                            "include_blocked": include_blocked,
                            "include_na": include_na,
                            "include_finding_summaries": include_finding_summaries,
                        }
                    )
                flash("ChatGPT handoff generated.", "success")
                return render_detail(record, handoff_path_value=str(record.get("handoff_path") or ""), handoff_markdown_value=written_handoff)
            except (OSError, IOError, PermissionError) as exc:
                app.logger.exception(
                    "validation_session_handoff_write_failed path=%s handoff_path=%s",
                    record_path,
                    output,
                )
                flash(f"Failed to generate validation handoff: {exc}", "warning")
                return render_detail(record, handoff_path_value="", handoff_markdown_value="")
        abort(400)
    return render_detail(record)


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
    if message.lower() in {"digest my thought box", "digest idea inventory", "digest idea orders", "digest sprint groups"}:
        preview = _preview_thought_items(_thought_box_items(digested_only=False))
        preview["review_mode"] = True
        return {
            "ok": True,
            "assistant_reply": "Digest Grouping Review ready. Review the tables before creating proposed sprint records.",
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
    thought_ids = [str(item) for item in (payload.get("selected_idea_ids") or payload.get("thought_ids") or []) if str(item).strip()]
    thought_paths = [str(item) for item in (payload.get("thought_paths") or []) if str(item).strip()]
    selected_only = bool(payload.get("selected_only"))
    if thought_ids:
        thoughts = _thoughts_by_ids(thought_ids)
    elif thought_paths:
        thoughts = _thoughts_by_paths(thought_paths)
    else:
        thoughts = _thought_box_items(digested_only=False)
    if selected_only and not (thought_ids or thought_paths):
        return {"ok": False, "error": "Select at least one raw idea before digesting."}, 400
    active_thoughts = _thought_box_items(digested_only=False)
    active_by_id = {_thought_item_fingerprint(item): item for item in active_thoughts}
    active_by_path = {item["path"]: item for item in active_thoughts}
    skipped_selected_ids = [thought_id for thought_id in thought_ids if thought_id not in active_by_id]
    skipped_selected_paths = [path for path in thought_paths if path not in active_by_path]
    if selected_only and not thoughts:
        return {"ok": False, "error": "Selected idea IDs no longer match active raw ideas."}, 400
    app.logger.info(
        "digest-preview selection ids=%s count=%s paths=%s selected_only=%s",
        thought_ids,
        len(thoughts),
        thought_paths,
        selected_only,
    )
    preview = _preview_thought_items(thoughts)
    app.logger.info(
        "digest-preview payload source_ideas=%s suggested_groups=%s",
        len(preview.get("active_items") or []),
        len(preview.get("sprint_groups") or []),
    )
    preview["review_mode"] = True
    preview["selection_mode"] = "selected" if selected_only and (thought_ids or thought_paths) else "all"
    preview["selected_thought_ids"] = [str(item) for item in thought_ids]
    preview["selected_idea_ids"] = [str(item) for item in thought_ids]
    preview["selected_thought_paths"] = [str(path) for path in thought_paths]
    preview["skipped_selected_thought_ids"] = skipped_selected_ids
    preview["skipped_selected_thought_paths"] = skipped_selected_paths
    preview["source_idea_count"] = len(thoughts)
    preview["selected_idea_count"] = len(thoughts)
    return {"ok": True, "digest_preview": preview, "thought_count": len(thoughts), "assistant_reply": "Review the suggested grouping before creating proposed sprint records."}


@app.route("/api/assistant/create-proposed-sprints", methods=["POST"])
@_require_worklog_session
def assistant_create_proposed_sprints():
    payload = request.get_json(silent=True) or {}
    preview = payload.get("digest_preview") or {}
    action = (payload.get("action") or "accept_suggested").strip().lower()
    if action == "cancel":
        return {"ok": True, "created_proposed_sprints": [], "assistant_reply": "Digest grouping review canceled."}
    groups = [group for group in preview.get("sprint_groups") or [] if isinstance(group, dict)]
    if not groups:
        return {"ok": False, "error": "No suggested groups were available to create proposed sprints."}, 400
    if action == "combine_all":
        created_proposals = _create_proposed_sprints_from_preview(preview, "combine_all")
    else:
        created_proposals = _create_proposed_sprints_from_preview(preview, "suggested")
    created_sprints = [{"proposal_id": proposal["proposal_id"], "sprint_code": proposal["sprint_code"], "path": proposal.get("path")} for proposal in created_proposals]
    sprint_detail_urls = [url_for("sprint_detail", sprint_id=proposal["proposal_id"]) for proposal in created_proposals]
    duplicate_existing = next((proposal for proposal in created_proposals if proposal.get("_existing_duplicate")), None)
    return {
        "ok": True,
        "created_proposed_sprints": created_sprints,
        "sprint_detail_urls": sprint_detail_urls,
        "sprint_queue_url": url_for("sprints", status="proposed"),
        "assistant_reply": (
            "A sprint already exists for these ideas."
            if duplicate_existing
            else "Proposed sprint groups created. Review them in Sprint Queue."
        ),
        "existing_sprint_url": sprint_detail_urls[0] if duplicate_existing and sprint_detail_urls else "",
    }


@app.route("/api/assistant/approve-digest", methods=["POST"])
@_require_worklog_session
def assistant_approve_digest():
    payload = request.get_json(silent=True) or {}
    return assistant_create_proposed_sprints()


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
