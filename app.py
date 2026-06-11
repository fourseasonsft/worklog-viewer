from __future__ import annotations

import os
from functools import wraps
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
    cards = [
        {"title": "Current Focus", "path": "00-dashboard/current-focus.md"},
        {"title": "Where We Left Off", "path": "00-dashboard/where-we-left-off.md"},
        {"title": "Blockers", "path": "00-dashboard/blockers.md"},
        {"title": "Next Actions", "path": "00-dashboard/next-actions.md"},
        {"title": "Today’s Daily Log", "path": _latest_daily_log() or "01-daily-logs/2026/06/2026-06-11.md"},
        {"title": "Inbox / New Items", "path": "04-inbox/new/example-inbox-item.md"},
    ]
    rendered = []
    for card in cards:
        source = _read_markdown(card["path"])
        rendered.append({**card, "html": _render_markdown(source)})
    return render_template("dashboard.html", cards=rendered)


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
