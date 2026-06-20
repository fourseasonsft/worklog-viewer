from __future__ import annotations

import os
import re
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
INTAKE_TYPE_BUCKETS = {
    "bug": "bugs",
    "feature": "features",
    "support": "support",
    "note": "new",
    "blocker": "new",
    "thought": "new",
    "customer-request": "new",
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
        {"label": "Dashboard", "endpoint": "dashboard"},
        {"label": "Portfolio Status", "endpoint": "view_file", "args": {"relative_path": "00-dashboard/portfolio-status.md"}},
        {"label": "Engineering Priorities", "endpoint": "view_file", "args": {"relative_path": "00-dashboard/engineering-priorities.md"}},
        {"label": "Roadmap", "endpoint": "roadmap"},
        {"label": "Active Work", "endpoint": "active_work"},
        {"label": "Daily Logs", "endpoint": "daily_logs"},
        {"label": "Runbooks", "endpoint": "runbooks"},
        {"label": "Inbox", "endpoint": "inbox"},
        {"label": "Inbox / New", "endpoint": "inbox_new"},
        {"label": "Inbox / Bugs", "endpoint": "inbox_bugs"},
        {"label": "Inbox / Features", "endpoint": "inbox_features"},
        {"label": "Inbox / Support", "endpoint": "inbox_support"},
        {"label": "Inbox / Closed", "endpoint": "inbox_closed"},
        {"label": "Decisions", "endpoint": "category_view", "category": "04-decisions"},
        {"label": "Release Notes", "endpoint": "category_view", "category": "05-release-notes"},
        {"label": "Ideas", "endpoint": "category_view", "category": "06-ideas"},
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


def _summarize_active_work_file(relative_path: str, title: str) -> dict[str, object]:
    source_path = WORKLOG_ROOT / relative_path
    text = source_path.read_text(encoding="utf-8")
    sprint_text = _extract_section_text(text, "Current Sprint / Focus")
    blockers_text = _extract_section_text(text, "Blockers")
    last_updated_text = _extract_section_text(text, "Last Updated")
    last_updated = _extract_first_value(last_updated_text) or _format_file_timestamp(source_path)
    return {
        "title": title,
        "path": relative_path,
        "current_sprint_html": _render_markdown(sprint_text or "_No current sprint recorded._"),
        "blockers_count": _count_meaningful_bullets(blockers_text),
        "last_updated": last_updated,
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
    top_documents = _dashboard_documents()
    portfolio_status = top_documents[0]
    engineering_priorities = top_documents[1]
    current_focus = top_documents[2]
    next_actions = top_documents[3]
    where_we_left_off = top_documents[4]
    latest_daily_log_path = _latest_daily_log() or "01-daily-logs/2026/06/2026-06-11.md"
    latest_daily_log = {
        "title": "Today’s Daily Log",
        "path": latest_daily_log_path,
        "html": _render_markdown(_read_markdown(latest_daily_log_path)),
    }

    active_work = [_summarize_active_work_file(item["path"], item["title"]) for item in ACTIVE_WORK_FILES]
    counts = _dashboard_counts()
    inbox_items = _recent_inbox_items()
    intake_counts = _dashboard_intake_counts()
    intake_items = _all_structured_inbox_items()[:8]
    plain_mode = _intake_plain_mode_enabled()
    summary_cards = [
        {"label": "Open Bugs", "count": counts["open_bugs"], "href": url_for("inbox_bugs"), "hint": "Current bug items"},
        {"label": "Open Features", "count": counts["open_features"], "href": url_for("inbox_features"), "hint": "Requested enhancements"},
        {"label": "Open Support Items", "count": counts["open_support"], "href": url_for("inbox_support"), "hint": "Support and operational issues"},
        {"label": "Open New Inbox Items", "count": counts["open_new"], "href": url_for("inbox_new"), "hint": "Fresh triage queue"},
        {"label": "Active Applications", "count": counts["active_applications"], "href": url_for("active_work"), "hint": "Tracked work streams"},
        {"label": "Blockers", "count": counts["blockers"], "href": f"{url_for('dashboard')}#where-we-left-off", "hint": "Current blocking items"},
    ]

    quick_links = [
        {"label": "Portfolio Status", "href": "#portfolio-status"},
        {"label": "Engineering Priorities", "href": "#engineering-priorities"},
        {"label": "Current Focus", "href": "#current-focus"},
        {"label": "Next Actions", "href": "#next-actions"},
        {"label": "Daily Logs", "href": url_for("daily_logs")},
        {"label": "Roadmap", "href": url_for("roadmap")},
        {"label": "Inbox", "href": url_for("inbox")},
        {"label": "Runbooks", "href": url_for("runbooks")},
        {"label": "Active Work", "href": url_for("active_work")},
        {"label": "Intake", "href": url_for("intake")},
    ]

    return render_template(
        "dashboard.html",
        counts=counts,
        intake_counts=intake_counts,
        intake_items=intake_items,
        plain_mode=plain_mode,
        quick_links=quick_links,
        summary_cards=summary_cards,
        portfolio_status=portfolio_status,
        engineering_priorities=engineering_priorities,
        current_focus=current_focus,
        next_actions=next_actions,
        where_we_left_off=where_we_left_off,
        latest_daily_log=latest_daily_log,
        active_work=active_work,
        inbox_items=inbox_items,
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
@_require_worklog_session
def inbox_new():
    return render_template("listing.html", title="Inbox / New", items=_category_files("04-inbox/new"))


@app.route("/inbox/bugs")
@_require_worklog_session
def inbox_bugs():
    return render_template("listing.html", title="Inbox / Bugs", items=_category_files("04-inbox/bugs"))


@app.route("/inbox/features")
@_require_worklog_session
def inbox_features():
    return render_template("listing.html", title="Inbox / Features", items=_category_files("04-inbox/features"))


@app.route("/inbox/support")
@_require_worklog_session
def inbox_support():
    return render_template("listing.html", title="Inbox / Support", items=_category_files("04-inbox/support"))


@app.route("/inbox/closed")
@_require_worklog_session
def inbox_closed():
    return render_template("listing.html", title="Inbox / Closed", items=_category_files("04-inbox/closed"))


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
