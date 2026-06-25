#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import app as viewer_app


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(text: str) -> str:
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


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _unquote(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    return value


def _session_dir(worklog_root: Path) -> Path:
    return worklog_root / "07-validation-sessions"


def _hand_off_dir(worklog_root: Path) -> Path:
    return worklog_root / "05-sprint-handoffs" / "validation-sessions"


def _session_path(worklog_root: Path, slug: str) -> Path:
    return _session_dir(worklog_root) / f"{slug}.md"


def _resolve_session_file(worklog_root: Path, session_ref: str) -> Path:
    candidate = Path(session_ref)
    if candidate.is_absolute():
        return candidate
    if candidate.suffix == ".md" and candidate.parts[:1] == ("07-validation-sessions",):
        return worklog_root / candidate
    if candidate.suffix == ".md" and candidate.parent != Path("."):
        return worklog_root / candidate
    return _session_path(worklog_root, session_ref)


def _seed_session_payload() -> dict[str, object]:
    payload = dict(SEED_SESSION)
    payload["created_at"] = _now_iso()
    payload["updated_at"] = payload["created_at"]
    return payload


def _default_session_payload(title: str, slug: str, app: str, run: str, track: str, release: str, status: str) -> dict[str, object]:
    now = _now_iso()
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
        "items": [],
    }


def _serialize_session(data: dict[str, object]) -> str:
    lines: list[str] = ["---"]
    for key in ["title", "slug", "app", "run", "track", "release", "status", "created_at", "updated_at", "completed_at", "blocked_at", "handoff_path"]:
        value = str(data.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {_quote(value)}")
    items = list(data.get("items") or [])
    lines.append("items:")
    for item in items:
        lines.append(f"  - id: {_quote(str(item.get('id') or ''))}")
        for key in ["section", "description", "status", "notes", "finding_severity", "finding_summary"]:
            lines.append(f"    {key}: {_quote(str(item.get(key) or ''))}")
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


def _parse_session(text: str) -> dict[str, object]:
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
            data[key.strip()] = _unquote(value.strip())
            continue
        if line.startswith("  - "):
            if current_item:
                items.append(current_item)
            current_item = {}
            key, _, value = line[4:].partition(":")
            current_item[key.strip()] = _unquote(value.strip())
            continue
        if current_item is None:
            continue
        key, _, value = line.strip().partition(":")
        current_item[key.strip()] = _unquote(value.strip())
    if current_item:
        items.append(current_item)
    data["items"] = items
    return data


def _read_session(worklog_root: Path, session_ref: str) -> tuple[Path, dict[str, object]]:
    path = _resolve_session_file(worklog_root, session_ref)
    if not path.exists():
        raise FileNotFoundError(path)
    return path, _parse_session(path.read_text(encoding="utf-8"))


def _write_session(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_serialize_session(data), encoding="utf-8")


def _validate_item(data: dict[str, object]) -> None:
    status = str(data.get("status") or "").strip()
    if status and status not in ALLOWED_ITEM_STATUSES:
        raise ValueError(f"Invalid item status: {status}")
    severity = str(data.get("finding_severity") or "").strip()
    if severity and severity not in ALLOWED_FINDING_SEVERITIES:
        raise ValueError(f"Invalid finding severity: {severity}")


def _find_item(items: list[dict[str, object]], item_id: str) -> dict[str, object]:
    for item in items:
        if str(item.get("id") or "").strip() == item_id:
            return item
    raise KeyError(f"Validation item not found: {item_id}")


def _seed_profile_or_error(profile: str | None) -> dict[str, object]:
    if profile and profile.strip().lower() != SEED_PROFILE:
        raise ValueError(f"Unknown seed profile: {profile}")
    return _seed_session_payload()


def _session_summary(data: dict[str, object]) -> Counter[str]:
    return Counter(str(item.get("status") or "pending") for item in data.get("items") or [])


def _findings_by_severity(data: dict[str, object]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for item in data.get("items") or []:
        severity = str(item.get("finding_severity") or "").strip()
        if severity:
            counter[severity] += 1
    return counter


def _generate_handoff_markdown(data: dict[str, object], session_path: Path | None = None) -> str:
    counts = _session_summary(data)
    findings = _findings_by_severity(data)
    items = list(data.get("items") or [])
    failed = [item for item in items if str(item.get("status") or "") == "fail"]
    blocked = [item for item in items if str(item.get("status") or "") == "blocked"]
    deferred = [item for item in items if str(item.get("status") or "") in {"pending", "not_applicable"}]
    recommended = "Review failed items and resolve the blocker before the next validation pass."
    if blocked:
        recommended = "Unblock the blocked items before retesting the session."
    elif not failed and counts.get("pending"):
        recommended = "Work through the remaining pending items and collect findings."
    elif not failed and not blocked and not counts.get("pending"):
        recommended = "Mark the session completed and move the validation results into the next handoff."
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
        "",
        "## Findings by Severity",
    ]
    if findings:
        for severity, count in sorted(findings.items()):
            lines.append(f"- {severity}: {count}")
    else:
        lines.append("- None recorded yet")
    lines.extend(
        [
            "",
            "## Failed Items",
        ]
    )
    if failed:
        for item in failed:
            lines.append(
                f"- {item.get('id')}: {item.get('section')} - {item.get('finding_summary') or item.get('description') or 'No summary recorded.'}"
            )
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Blocked Items")
    if blocked:
        for item in blocked:
            lines.append(f"- {item.get('id')}: {item.get('section')} - {item.get('finding_summary') or 'No summary recorded.'}")
    else:
        lines.append("- None")
    lines.append("")
    lines.append("## Deferred Items")
    if deferred:
        for item in deferred:
            lines.append(f"- {item.get('id')}: {item.get('section')} - {item.get('description') or 'No description recorded.'}")
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Recommended Next Action",
            recommended,
        ]
    )
    if session_path:
        lines.extend(["", f"- Session File: {session_path}"])
    return "\n".join(lines).rstrip() + "\n"


def _complete_session(data: dict[str, object]) -> dict[str, object]:
    now = _now_iso()
    data["status"] = "completed"
    data["updated_at"] = now
    data["completed_at"] = now
    return data


def _update_session_item(data: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    items = list(data.get("items") or [])
    item = _find_item(items, args.id)
    updates = {
        "section": args.section,
        "description": args.description,
        "status": args.status,
        "notes": args.notes,
        "finding_severity": args.finding_severity,
        "finding_summary": args.finding_summary,
    }
    for key, value in updates.items():
        if value is not None:
            item[key] = value
    _validate_item(item)
    data["items"] = items
    data["updated_at"] = _now_iso()
    return data


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Worklog operational validation sessions.")
    parser.add_argument("--worklog-root", default=str(viewer_app.WORKLOG_ROOT))
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a validation session markdown file.")
    create.add_argument("--title", default=SEED_SESSION["title"])
    create.add_argument("--slug")
    create.add_argument("--app", default=SEED_SESSION["app"])
    create.add_argument("--run", default=SEED_SESSION["run"])
    create.add_argument("--track", default=SEED_SESSION["track"])
    create.add_argument("--release", default=SEED_SESSION["release"])
    create.add_argument("--status", default="in_progress", choices=sorted(ALLOWED_SESSION_STATUSES))
    create.add_argument("--seed", choices=[SEED_PROFILE])
    create.add_argument("--json-output", action="store_true")

    update_item = subparsers.add_parser("update-item", help="Update an item in a validation session.")
    update_item.add_argument("--session", required=True)
    update_item.add_argument("--id", required=True)
    update_item.add_argument("--section")
    update_item.add_argument("--description")
    update_item.add_argument("--status", choices=sorted(ALLOWED_ITEM_STATUSES))
    update_item.add_argument("--notes")
    update_item.add_argument("--finding-severity", dest="finding_severity", choices=sorted(ALLOWED_FINDING_SEVERITIES))
    update_item.add_argument("--finding-summary", dest="finding_summary")
    update_item.add_argument("--json-output", action="store_true")

    handoff = subparsers.add_parser("generate-handoff", help="Generate a handoff from a validation session.")
    handoff.add_argument("--session", required=True)
    handoff.add_argument("--output")
    handoff.add_argument("--json-output", action="store_true")

    complete = subparsers.add_parser("complete", help="Mark a validation session completed.")
    complete.add_argument("--session", required=True)
    complete.add_argument("--json-output", action="store_true")

    return parser


def _resolve_worklog_root(raw_root: str) -> Path:
    root = Path(raw_root).expanduser().resolve()
    return root


def _handle_create(args: argparse.Namespace, root: Path) -> int:
    slug = args.slug.strip() if args.slug else _slugify(str(args.title or SEED_SESSION["title"]))
    path = _session_path(root, slug)
    if path.exists():
        raise FileExistsError(path)
    if args.seed:
        data = _seed_profile_or_error(args.seed)
        data["slug"] = slug
        data["title"] = str(args.title or data["title"])
        data["app"] = str(args.app or data["app"])
        data["run"] = str(args.run or data["run"])
        data["track"] = str(args.track or data["track"])
        data["release"] = str(args.release or data["release"])
        data["status"] = str(args.status or data["status"])
        data["updated_at"] = _now_iso()
    else:
        data = _default_session_payload(str(args.title), slug, str(args.app), str(args.run), str(args.track), str(args.release), str(args.status))
    _write_session(path, data)
    payload = {
        "created": True,
        "path": str(path),
        "slug": slug,
        "title": data["title"],
        "status": data["status"],
    }
    if args.json_output:
        print(json.dumps(payload))
    else:
        print(f"Created validation session at {path}")
    return 0


def _handle_update_item(args: argparse.Namespace, root: Path) -> int:
    path, data = _read_session(root, args.session)
    data = _update_session_item(data, args)
    _write_session(path, data)
    if args.json_output:
        print(json.dumps({"updated": True, "path": str(path), "item_id": args.id}))
    else:
        print(f"Updated validation session item {args.id} in {path}")
    return 0


def _handle_generate_handoff(args: argparse.Namespace, root: Path) -> int:
    path, data = _read_session(root, args.session)
    handoff_dir = _hand_off_dir(root)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    handoff_name = f"{data.get('slug') or _slugify(str(data.get('title') or 'validation-session'))}.md"
    if args.output:
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = (root / output).resolve()
        else:
            output = output.resolve()
    else:
        output = handoff_dir / handoff_name
    handoff_md = _generate_handoff_markdown(data, session_path=path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(handoff_md, encoding="utf-8")
    data["handoff_path"] = str(output.relative_to(root))
    data["updated_at"] = _now_iso()
    _write_session(path, data)
    payload = {
        "generated": True,
        "session": str(path),
        "handoff_path": str(output),
    }
    if args.json_output:
        print(json.dumps(payload))
    else:
        print(f"Generated handoff at {output}")
    return 0


def _handle_complete(args: argparse.Namespace, root: Path) -> int:
    path, data = _read_session(root, args.session)
    data = _complete_session(data)
    _write_session(path, data)
    if args.json_output:
        print(json.dumps({"completed": True, "path": str(path)}))
    else:
        print(f"Marked validation session completed at {path}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = _resolve_worklog_root(args.worklog_root)
    try:
        if args.command == "create":
            return _handle_create(args, root)
        if args.command == "update-item":
            return _handle_update_item(args, root)
        if args.command == "generate-handoff":
            return _handle_generate_handoff(args, root)
        if args.command == "complete":
            return _handle_complete(args, root)
        parser.error(f"Unsupported command: {args.command}")
    except (FileExistsError, FileNotFoundError, KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
