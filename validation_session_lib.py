from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ALLOWED_ITEM_STATUSES = {"pending", "pass", "fail", "blocked", "not_applicable"}
ALLOWED_FINDING_SEVERITIES = {"P0 App Blocker", "P1 Release Blocker", "P2 Defect", "P3 Polish", "Idea"}
ALLOWED_SESSION_STATUSES = {"in_progress", "completed", "blocked"}
SEED_PROFILE = "ims-warehouse-foundation-release-1.0"

SEED_SESSION = {
    "title": "IMS Warehouse Foundation Release 1.0 Validation",
    "slug": "ims-warehouse-foundation-release-1-0-validation",
    "app": "IMS",
    "run": "Enterprise Shipment Management",
    "track": "Warehouse Foundation",
    "release": "Release 1.0",
    "status": "in_progress",
    "items": [
        {
            "id": "restart-basic-health",
            "section": "Restart / Basic Health",
            "description": "Restart the IMS DEV stack and confirm the app comes up cleanly before validation work continues.",
            "status": "pass",
            "notes": "IMS DEV is already running and the validation session has a clean baseline.",
            "finding_severity": "",
            "finding_summary": "",
        },
        {
            "id": "internal-pallet-ids",
            "section": "Internal Pallet IDs",
            "description": "Verify the internal pallet ID generation and label paths are working for foundation validation.",
            "status": "pass",
            "notes": "Internal pallet IDs are complete and validated in DEV.",
            "finding_severity": "",
            "finding_summary": "",
        },
        {
            "id": "break-bulk-foundation",
            "section": "Break Bulk Foundation",
            "description": "Confirm the break bulk foundation is in place and ready for the intake wizard workflow.",
            "status": "pass",
            "notes": "Break Bulk Foundation is complete and validated in DEV.",
            "finding_severity": "",
            "finding_summary": "",
        },
        {
            "id": "break-bulk-intake-wizard",
            "section": "Break Bulk Intake Wizard",
            "description": "Validate the break bulk intake wizard save path and complete the Release 1.0 intake workflow.",
            "status": "fail",
            "notes": "Save fails with HTTP 400 when the wizard submits the current payload.",
            "finding_severity": "P1 Release Blocker",
            "finding_summary": "Break Bulk Intake Wizard save fails with HTTP 400.",
        },
        {
            "id": "validation-bad-inputs",
            "section": "Validation / Bad Inputs",
            "description": "Probe invalid or edge-case inputs for the intake wizard and break bulk save flow.",
            "status": "pending",
            "notes": "",
            "finding_severity": "",
            "finding_summary": "",
        },
        {
            "id": "regression-checks",
            "section": "Regression Checks",
            "description": "Confirm the completed foundation work still behaves after the intake wizard blocker is investigated.",
            "status": "pending",
            "notes": "",
            "finding_severity": "",
            "finding_summary": "",
        },
        {
            "id": "release-1-0-readiness-notes",
            "section": "Release 1.0 Readiness Notes",
            "description": "Capture readiness notes, remaining blockers, and any release observations for Warehouse Foundation.",
            "status": "pending",
            "notes": "Needs review once the intake wizard blocker is resolved.",
            "finding_severity": "",
            "finding_summary": "",
        },
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    text = text.strip().lower()
    chars: list[str] = []
    last_dash = False
    for char in text:
        if char.isalnum():
            chars.append(char)
            last_dash = False
        else:
            if not last_dash:
                chars.append("-")
                last_dash = True
    slug = "".join(chars).strip("-")
    return slug or "validation-session"


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def unquote(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def session_dir(worklog_root: Path) -> Path:
    return worklog_root / "07-validation-sessions"


def handoff_dir(worklog_root: Path) -> Path:
    return worklog_root / "05-sprint-handoffs" / "validation-sessions"


def session_path(worklog_root: Path, slug: str) -> Path:
    return session_dir(worklog_root) / f"{slug}.md"


def resolve_session_file(worklog_root: Path, session_ref: str) -> Path:
    candidate = Path(session_ref)
    if candidate.is_absolute():
        return candidate
    if candidate.suffix == ".md" and candidate.parts[:1] == ("07-validation-sessions",):
        return worklog_root / candidate
    if candidate.suffix == ".md" and candidate.parent != Path("."):
        return worklog_root / candidate
    return session_path(worklog_root, session_ref)


def seed_session_payload() -> dict[str, object]:
    payload = dict(SEED_SESSION)
    payload["created_at"] = now_iso()
    payload["updated_at"] = payload["created_at"]
    payload["final_recommendation"] = ""
    return payload


def default_session_payload(title: str, slug: str, app: str, run: str, track: str, release: str, status: str) -> dict[str, object]:
    now = now_iso()
    return {
        "title": title,
        "slug": slug,
        "app": app,
        "run": run,
        "track": track,
        "release": release,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "final_recommendation": "",
        "items": [],
    }


def normalize_item(item: dict[str, object]) -> dict[str, str]:
    return {
        "id": str(item.get("id") or "").strip(),
        "section": str(item.get("section") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "status": str(item.get("status") or "pending").strip() or "pending",
        "notes": str(item.get("notes") or "").strip(),
        "finding_severity": str(item.get("finding_severity") or "").strip(),
        "finding_summary": str(item.get("finding_summary") or "").strip(),
    }


def validate_item(data: dict[str, object]) -> None:
    status = str(data.get("status") or "").strip()
    if status and status not in ALLOWED_ITEM_STATUSES:
        raise ValueError(f"Invalid item status: {status}")
    severity = str(data.get("finding_severity") or "").strip()
    if severity and severity not in ALLOWED_FINDING_SEVERITIES:
        raise ValueError(f"Invalid finding severity: {severity}")


def serialize_session(data: dict[str, object]) -> str:
    lines: list[str] = ["---"]
    for key in ["title", "slug", "app", "run", "track", "release", "status", "created_at", "updated_at", "completed_at", "blocked_at", "handoff_path", "final_recommendation"]:
        value = str(data.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {quote(value)}")
    items = list(data.get("items") or [])
    lines.append("items:")
    for item in items:
        lines.append(f"  - id: {quote(str(item.get('id') or ''))}")
        for key in ["section", "description", "status", "notes", "finding_severity", "finding_summary"]:
            lines.append(f"    {key}: {quote(str(item.get(key) or ''))}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {data.get('title') or 'Validation Session'}")
    lines.append("")
    lines.append("## Session")
    for key, label in [
        ("slug", "Slug"),
        ("app", "App"),
        ("run", "Run"),
        ("track", "Track"),
        ("release", "Release"),
        ("status", "Status"),
        ("created_at", "Created"),
        ("updated_at", "Updated"),
        ("completed_at", "Completed"),
        ("blocked_at", "Blocked"),
        ("handoff_path", "Handoff"),
        ("final_recommendation", "Final Recommendation"),
    ]:
        value = str(data.get(key) or "").strip() or "Not recorded yet"
        lines.append(f"- {label}: {value}")
    lines.append("")
    lines.append("## Items")
    for item in data.get("items") or []:
        notes = str(item.get("notes") or "").replace("\\n", "\n").strip()
        lines.append(f"### {item.get('section') or 'Section'} / {item.get('id') or ''}")
        lines.append(f"- Description: {item.get('description') or ''}")
        lines.append(f"- Status: {item.get('status') or 'pending'}")
        lines.append(f"- Finding Severity: {item.get('finding_severity') or 'Not recorded yet'}")
        lines.append(f"- Finding Summary: {item.get('finding_summary') or 'Not recorded yet'}")
        lines.append("- Notes:")
        if notes:
            for note_line in notes.splitlines():
                lines.append(f"  - {note_line}")
        else:
            lines.append("  - Not recorded yet")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def parse_session(text: str) -> dict[str, object]:
    if not text.startswith("---\n"):
        raise ValueError("Validation session file is missing YAML frontmatter.")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Validation session file is missing the closing YAML delimiter.")
    frontmatter = text[4:end]
    data: dict[str, object] = {}
    items: list[dict[str, str]] = []
    current_item: dict[str, str] | None = None
    in_items = False
    for raw_line in frontmatter.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line == "items:":
            in_items = True
            continue
        if not in_items:
            key, _, value = line.partition(":")
            data[key.strip()] = unquote(value.strip())
            continue
        if line.startswith("  - "):
            if current_item:
                items.append(current_item)
            current_item = {}
            key, _, value = line[4:].partition(":")
            current_item[key.strip()] = unquote(value.strip())
            continue
        if current_item is None:
            continue
        key, _, value = line.strip().partition(":")
        current_item[key.strip()] = unquote(value.strip())
    if current_item:
        items.append(current_item)
    data["items"] = items
    return data


def write_session(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_session(data), encoding="utf-8")


def read_session(worklog_root: Path, session_ref: str) -> tuple[Path, dict[str, object]]:
    path = resolve_session_file(worklog_root, session_ref)
    if not path.exists():
        raise FileNotFoundError(path)
    return path, parse_session(path.read_text(encoding="utf-8"))


def update_item(data: dict[str, object], item_id: str, updates: dict[str, object]) -> dict[str, object]:
    items = list(data.get("items") or [])
    for item in items:
        if str(item.get("id") or "").strip() == item_id:
            item.update({key: value for key, value in updates.items() if value is not None})
            validate_item(item)
            data["items"] = items
            data["updated_at"] = now_iso()
            return data
    raise KeyError(f"Validation item not found: {item_id}")


def complete_session(data: dict[str, object]) -> dict[str, object]:
    now = now_iso()
    data["status"] = "completed"
    data["updated_at"] = now
    data["completed_at"] = now
    return data


def session_status_counts(data: dict[str, object]) -> Counter[str]:
    return Counter(str(item.get("status") or "pending") for item in data.get("items") or [])


def findings_by_severity(data: dict[str, object]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in data.get("items") or []:
        severity = str(item.get("finding_severity") or "").strip()
        if severity:
            counter[severity] += 1
    return counter


def _status_label(status: str) -> str:
    mapping = {
        "pass": "PASS",
        "fail": "FAIL",
        "pending": "PENDING",
        "blocked": "BLOCKED",
        "not_applicable": "N/A",
    }
    return mapping.get(status, status.upper() or "PENDING")


def _item_should_include(status: str, *, include_passed: bool, include_pending: bool, include_blocked: bool, include_na: bool) -> bool:
    if status == "pass":
        return include_passed
    if status == "pending":
        return include_pending
    if status == "blocked":
        return include_blocked
    if status == "not_applicable":
        return include_na
    return True


def generate_handoff_markdown(
    data: dict[str, object],
    session_path_value: Path | None = None,
    *,
    include_notes: bool = True,
    include_passed: bool = True,
    include_pending: bool = True,
    include_blocked: bool = True,
    include_na: bool = True,
    include_finding_summaries: bool = True,
) -> str:
    counts = session_status_counts(data)
    findings = findings_by_severity(data)
    items = list(data.get("items") or [])
    included_items = [
        item
        for item in items
        if _item_should_include(
            str(item.get("status") or "pending"),
            include_passed=include_passed,
            include_pending=include_pending,
            include_blocked=include_blocked,
            include_na=include_na,
        )
    ]
    failed = [item for item in included_items if str(item.get("status") or "") == "fail"]
    blocked = [item for item in included_items if str(item.get("status") or "") == "blocked"]
    deferred = [item for item in included_items if str(item.get("status") or "") in {"pending", "not_applicable"}]
    recommended = "Review failed items and resolve the blocker before the next validation pass."
    if blocked:
        recommended = "Unblock the blocked items before retesting the session."
    elif not failed and counts.get("pending"):
        recommended = "Work through the remaining pending items and collect findings."
    elif not failed and not blocked and not counts.get("pending"):
        recommended = "Mark the session completed and move the validation results into the next handoff."
    release_recommendation = "Not recorded yet"
    if counts.get("fail") or counts.get("blocked"):
        release_recommendation = "Do not ship until the failure or blocker is resolved."
    elif counts.get("pending"):
        release_recommendation = "Continue validation before recommending release."
    else:
        release_recommendation = "Ready for release consideration after review."
    lines = [
        f"# Validation Session Handoff: {data.get('title') or 'Validation Session'}",
        "",
        "## Session Summary",
        f"- Session Title: {data.get('title') or 'Validation Session'}",
        f"- Session Status: {data.get('status') or 'in_progress'}",
        f"- App: {data.get('app') or 'Not recorded yet'}",
        f"- Run: {data.get('run') or 'Not recorded yet'}",
        f"- Track: {data.get('track') or 'Not recorded yet'}",
        f"- Release: {data.get('release') or 'Not recorded yet'}",
        f"- Pass Count: {counts.get('pass', 0)}",
        f"- Fail Count: {counts.get('fail', 0)}",
        f"- Blocked Count: {counts.get('blocked', 0)}",
        f"- Pending Count: {counts.get('pending', 0)}",
        f"- N/A Count: {counts.get('not_applicable', 0)}",
        "",
        "## Findings by Severity",
    ]
    if findings:
        for severity, count in sorted(findings.items()):
            lines.append(f"- {severity}: {count}")
    else:
        lines.append("- None recorded yet")
    lines.extend(["", "## Validation Items"])
    if included_items:
        for item in included_items:
            status = str(item.get("status") or "pending")
            lines.append(f"### {item.get('section') or 'Section'}")
            lines.append(f"- {('✔' if status == 'pass' else '✖' if status == 'fail' else '⚠' if status == 'blocked' else '•')} {item.get('description') or 'No description recorded.'}")
            lines.append(f"- Status: {_status_label(status)}")
            if include_notes:
                lines.append("  - Notes:")
                notes = str(item.get('notes') or '').strip() or 'Not recorded yet'
                for line in notes.splitlines():
                    lines.append(f"    {line}")
            if status in {"fail", "blocked"} or include_finding_summaries:
                lines.append(f"- Finding Severity: {item.get('finding_severity') or 'Not recorded yet'}")
                lines.append(f"- Finding Summary: {item.get('finding_summary') or 'Not recorded yet'}")
            lines.append("")
    else:
        lines.append("- None")
    lines.extend(["", "## Release Recommendation", release_recommendation, "", "## Recommended Next Action", recommended])
    if session_path_value:
        lines.extend(["", f"- Session File: {session_path_value}"])
    return "\n".join(lines).rstrip() + "\n"


def generate_ai_prompt(data: dict[str, object], handoff_text: str) -> str:
    return "\n".join(
        [
            "Analyze the following Operational Validation Session.",
            "",
            "Please:",
            "",
            "• Summarize the findings.",
            "• Identify probable root causes.",
            "• Group related issues.",
            "• Recommend implementation order.",
            "• Identify technical debt.",
            "• Identify regression risks.",
            "• Recommend release readiness.",
            "• Produce a prioritized implementation plan.",
            "",
            "=== VALIDATION HANDOFF ===",
            "",
            handoff_text.rstrip(),
            "",
        ]
    )


def seed_profile_or_error(profile: str | None) -> dict[str, object]:
    if profile and profile.strip().lower() != SEED_PROFILE:
        raise ValueError(f"Unknown seed profile: {profile}")
    return seed_session_payload()
