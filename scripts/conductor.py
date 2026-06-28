#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_WORKLOG_ROOT = Path("/opt/fsftdev/fsft-worklog")
COMMAND_LOG_RELATIVE = Path("08-conductor/command-log.jsonl")
NOTIFICATIONS_RELATIVE = Path("04-inbox/notifications")
ISSUES_RELATIVE = Path("04-inbox/requests")


@dataclass(slots=True)
class CommandContext:
    worklog_root: Path
    actor: str
    source: str


def _resolve_root(raw_root: str | None) -> Path:
    return Path(raw_root or DEFAULT_WORKLOG_ROOT).expanduser().resolve()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _first_nonempty_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^-\s*([^:]+):\s*(.*)$", line.strip())
        if match:
            values[match.group(1).strip().lower()] = match.group(2).strip()
    return values


def _active_work_files(root: Path) -> list[Path]:
    work_dir = root / "03-active-work"
    if not work_dir.exists():
        return []
    return sorted([path for path in work_dir.glob("*.md") if path.is_file()])


def _current_focus_file(root: Path) -> Path | None:
    path = root / "00-dashboard" / "current-focus.md"
    return path if path.exists() else None


def _sprint_files(root: Path) -> list[Path]:
    sprint_root = root / "06-sprints"
    if not sprint_root.exists():
        return []
    return sorted([path for path in sprint_root.rglob("*.md") if path.is_file() and path.name != "README.md"], reverse=True)


def _request_files(root: Path) -> list[Path]:
    request_dir = root / "04-inbox" / "requests"
    if not request_dir.exists():
        return []
    return sorted([path for path in request_dir.rglob("*.md") if path.is_file()], reverse=True)


def _work_order_files(root: Path) -> list[Path]:
    work_order_dir = root / "07-work-orders"
    if not work_order_dir.exists():
        return []
    return sorted([path for path in work_order_dir.glob("*.md") if path.is_file()], reverse=True)


def _parse_sprint_record(path: Path) -> dict[str, str]:
    text = _read_text(path)
    meta = _parse_key_values(text)
    title = _first_nonempty_heading(text) or path.stem.replace("-", " ").title()
    return {
        "path": str(path),
        "title": title,
        "sprint_code": meta.get("sprint code") or meta.get("sprint_code") or meta.get("code") or path.stem.split("-", 1)[0],
        "status": meta.get("status") or "",
        "app": meta.get("app product") or meta.get("app") or "",
        "recommended_first_step": meta.get("recommended first step") or meta.get("recommended_first_step") or "",
        "notes": meta.get("notes") or "",
    }


def _parse_shortcode_request(path: Path) -> dict[str, str]:
    text = _read_text(path)
    meta = _parse_key_values(text)
    title = _first_nonempty_heading(text) or path.stem.replace("-", " ").title()
    shortcode = meta.get("shortcode") or meta.get("result_shortcode") or meta.get("request_shortcode") or ""
    return {
        "path": str(path),
        "title": title,
        "request_id": meta.get("request_id") or str(path.relative_to(path.parents[2])),
        "requester_email": meta.get("requester_email") or "",
        "shortcode": shortcode.strip(),
        "text": text,
    }


def _parse_work_order_packet(path: Path) -> dict[str, object]:
    text = _read_text(path)
    meta = _parse_key_values(text)
    title = _first_nonempty_heading(text) or path.stem.replace("-", " ").title()
    pending_follow_ups: list[str] = []
    prerequisite_states: list[dict[str, str]] = []
    current_section: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            continue
        if current_section == "pending follow-ups" and line.startswith("- "):
            item = line[2:].strip()
            if item:
                pending_follow_ups.append(item)
        if current_section in {"prerequisites", "prerequisite status"} and line.startswith("- "):
            item = line[2:].strip()
            if ":" in item:
                key, value = item.split(":", 1)
                prerequisite_states.append({"name": key.strip(), "state": value.strip()})
    return {
        "path": str(path),
        "title": title,
        "work_order_id": meta.get("work order id") or path.stem,
        "status": meta.get("status") or "",
        "requested_by": meta.get("requested by") or "",
        "pending_follow_ups": pending_follow_ups,
        "prerequisites": prerequisite_states,
        "text": text,
    }


def _work_order_prerequisites_complete(work_order: dict[str, object]) -> bool:
    prerequisites = work_order.get("prerequisites") or []
    if not prerequisites:
        return True
    for prerequisite in prerequisites:
        state = str(prerequisite.get("state") or "").strip().lower()
        if state not in {"complete", "completed", "done", "resolved", "closed"}:
            return False
    return True


def _advance_completed_follow_up(work_order: dict[str, object]) -> dict[str, object]:
    if _work_order_prerequisites_complete(work_order):
        pending = list(work_order.get("pending_follow_ups") or [])
        if pending:
            work_order = {**work_order}
            work_order["pending_follow_ups"] = pending[1:]
            work_order["completed_follow_up"] = pending[0]
    return work_order


def _find_sprint(root: Path, code: str) -> dict[str, str] | None:
    normalized = code.strip().lower()
    for path in _sprint_files(root):
        record = _parse_sprint_record(path)
        if record["sprint_code"].strip().lower() == normalized:
            return record
    return None


def _find_request_by_shortcode(root: Path, shortcode: str) -> dict[str, str] | None:
    normalized = shortcode.strip().lower()
    if not normalized:
        return None
    for path in _request_files(root):
        record = _parse_shortcode_request(path)
        haystack = "\n".join([record["title"], record["text"], record["request_id"]]).lower()
        if record["shortcode"].lower() == normalized or normalized in haystack:
            return record
    return None


def _find_work_order(root: Path, work_order_id: str) -> dict[str, object] | None:
    normalized = work_order_id.strip().lower()
    if not normalized:
        return None
    for path in _work_order_files(root):
        record = _parse_work_order_packet(path)
        haystack = "\n".join([record["title"], record["text"], record["work_order_id"]]).lower()
        if record["work_order_id"].strip().lower() == normalized or normalized in haystack:
            return _advance_completed_follow_up(record)
    return None


def _active_sprint_files(root: Path) -> list[Path]:
    active_dir = root / "06-sprints" / "active"
    if not active_dir.exists():
        return []
    return sorted([path for path in active_dir.glob("*.md") if path.is_file()], reverse=True)


def _seed_follow_up_from_sprint(root: Path, sprint_record: dict[str, str]) -> Path | None:
    sprint_code = (sprint_record.get("sprint_code") or "").strip()
    if not sprint_code:
        return None
    work_order_path = root / "07-work-orders" / f"{sprint_code}.md"
    if work_order_path.exists():
        return work_order_path
    recommended_first_step = (sprint_record.get("recommended_first_step") or "").strip()
    if not recommended_first_step:
        return None
    work_order_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(
        [
            f"# {sprint_code}",
            "",
            "Status: Requested",
            f"Created: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            f"Requested By: {sprint_record.get('app') or 'Worklog'}",
            "Primary App: Worklog",
            "Secondary System: Conductor",
            "Related Codex Shortcode: `/codex:fsft-work-order`",
            "",
            "## Objective",
            "",
            recommended_first_step,
            "",
            "## Why This Work Order Exists",
            "",
            "Sprint activation should seed the next known implementation step as a pending follow-up so `#/work-order fu <SPRINT-ID>` can execute immediately.",
            "",
            "## Pending Follow-Ups",
            "",
            f"- {recommended_first_step}",
        ]
    )
    _write_atomic_text(work_order_path, body + "\n")
    return work_order_path


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_shortcode_result(root: Path, shortcode: str, request: dict[str, str] | None, result_text: str) -> Path:
    _ensure_dir(root / NOTIFICATIONS_RELATIVE)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", shortcode.strip().lower()).strip("-") or "shortcode"
    target = root / NOTIFICATIONS_RELATIVE / f"{timestamp}-shortcode-result-{slug}.md"
    body_lines = [
        "# Notification: shortcode_result",
        "",
        f"- request_id: {request['request_id'] if request else ''}",
        f"- request_title: {request['title'] if request else ''}",
        f"- email: {request['requester_email'] if request else ''}",
        "- notification_type: shortcode_result",
        "- status: complete",
        f"- sent_at: ",
        f"- generated_at: {datetime.now(timezone.utc).isoformat()}",
        "- error_message: ",
        f"- subject: Shortcode result for {shortcode}",
        f"- idea_path: ",
        f"- sprint_code: ",
        f"- sprint_path: ",
        "",
        "## Body",
        f"Shortcode: {shortcode}",
        f"Result shortcode: {result_text}",
    ]
    if request:
        body_lines.extend(["", f"Source request: {request['path']}"])
    target.write_text("\n".join(body_lines) + "\n", encoding="utf-8")
    return target


def _write_atomic_text(path: Path, content: str) -> None:
    _ensure_dir(path.parent)
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _work_order_issue_artifact(root: Path, work_order_id: str, title: str, objective: str) -> Path:
    target = root / ISSUES_RELATIVE / f"{work_order_id}.md"
    body = "\n".join(
        [
            f"# GitHub Issue: {title}",
            "",
            f"- issue_id: {work_order_id}",
            "- issue_type: work_order_issuance",
            "- status: open",
            f"- work_order_id: {work_order_id}",
            f"- objective: {objective}",
            "",
            "## Body",
            f"Work Order ID: {work_order_id}",
            f"Objective: {objective}",
        ]
    )
    _write_atomic_text(target, body + "\n")
    return target


def _work_order_packet_artifact(root: Path, work_order_id: str, title: str, objective: str) -> Path:
    target = root / "07-work-orders" / f"{work_order_id}.md"
    body = "\n".join(
        [
            f"# {work_order_id}",
            "",
            "Status: Requested",
            f"Created: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            "Requested By: David",
            "Primary App: Worklog",
            "Secondary System: Conductor",
            "Related Codex Shortcode: `/codex:fsft-work-order`",
            "",
            "## Objective",
            "",
            objective,
            "",
            "## Why This Work Order Exists",
            "",
            "Transactional issuance should create both the GitHub Issue and the Git-backed Work Order packet, or fail with no partial state.",
            "",
            "## Completion Criteria",
            "",
            "- The GitHub Issue exists.",
            "- The Git-backed Work Order packet exists.",
            "- `#/work-order <WO-ID>` resolves immediately after issuance.",
        ]
    )
    _write_atomic_text(target, body + "\n")
    return target


def issue_work_order(root: Path, work_order_id: str, title: str, objective: str) -> dict[str, object]:
    issue_path: Path | None = None
    work_order_path: Path | None = None
    try:
        issue_path = _work_order_issue_artifact(root, work_order_id, title, objective)
        work_order_path = _work_order_packet_artifact(root, work_order_id, title, objective)
    except Exception:
        if issue_path and issue_path.exists():
            issue_path.unlink()
        if work_order_path and work_order_path.exists():
            work_order_path.unlink()
        raise
    return {
        "work_order_id": work_order_id,
        "issue_path": str(issue_path.relative_to(root)),
        "work_order_path": str(work_order_path.relative_to(root)),
    }


def _report_today(root: Path) -> dict[str, object]:
    active_files = _active_work_files(root)
    current_focus_path = _current_focus_file(root)
    current_focus = _read_text(current_focus_path) if current_focus_path else ""
    current_focus_title = _first_nonempty_heading(current_focus) if current_focus else ""
    open_sprints = [record for record in (_parse_sprint_record(path) for path in _sprint_files(root)) if record.get("status", "").lower() in {"proposed", "approved", "active", "staged"}]
    return {
        "current_context": {
            "current_focus": current_focus_title or "Current focus not recorded",
            "active_work_count": len(active_files),
            "active_work_items": [path.stem.replace("-", " ").title() for path in active_files],
        },
        "status": {
            "open_sprints": len(open_sprints),
            "latest_sprint": open_sprints[0] if open_sprints else None,
        },
        "what_changed": [
            "No live mutation performed.",
            "This command only reads the current Worklog state.",
        ],
        "open_decisions": [],
        "risks": [
            "Operational status is derived from markdown files and may lag behind external work.",
        ],
        "next_recommended_actions": [
            "Brief ChatGPT on current focus before changing scope.",
            "Review any active sprint records before planning a new operation.",
        ],
        "exact_question_for_chatgpt": "What should Conductor help the engineer decide next based on the current Worklog state?",
    }


def _brief_current(root: Path) -> dict[str, object]:
    current_focus_path = _current_focus_file(root)
    current_focus_text = _read_text(current_focus_path) if current_focus_path else ""
    active_files = _active_work_files(root)
    return {
        "current_context": {
            "artifact": "00-dashboard/current-focus.md" if current_focus_path else None,
            "summary": _first_nonempty_heading(current_focus_text) or "Current focus not recorded",
            "active_work_items": [path.stem.replace("-", " ").title() for path in active_files],
        },
        "status": {
            "active_work_count": len(active_files),
            "current_focus_path": str(current_focus_path) if current_focus_path else None,
        },
        "what_changed": [],
        "open_decisions": [
            "Which engineering operation should be prioritized next?",
        ],
        "risks": [
            "Attention is the scarce resource; avoid expanding scope without a decision.",
        ],
        "next_recommended_actions": [
            "Review the current focus document.",
            "Check the engineering priorities document if the focus is unclear.",
        ],
        "exact_question_for_chatgpt": "Given the current focus, what should Conductor brief the engineer on next?",
    }


def _brief_sprint(root: Path, sprint_code: str) -> dict[str, object]:
    sprint = _find_sprint(root, sprint_code)
    if not sprint:
        raise FileNotFoundError(f"Sprint not found: {sprint_code}")
    return {
        "current_context": {
            "artifact": sprint["path"],
            "sprint_code": sprint["sprint_code"],
            "title": sprint["title"],
            "app": sprint["app"] or "Not recorded",
        },
        "status": {
            "sprint_status": sprint["status"] or "Not recorded",
        },
        "what_changed": [],
        "open_decisions": [
            "Is this sprint still the correct engineering priority?",
        ],
        "risks": [
            "If the record is stale, the brief may not match the live engineering state.",
        ],
        "next_recommended_actions": [
            "Review the sprint file and related handoff.",
            "Update the sprint record if the status is outdated.",
        ],
        "exact_question_for_chatgpt": f"What should Conductor tell the engineer about sprint {sprint_code}?",
    }


def _log_command(ctx: CommandContext, command: str, target_artifact: str | None, input_payload: dict[str, object], output_summary: str, changed_files: list[str], errors: list[str], approval_status: str = "not_required") -> None:
    log_path = ctx.worklog_root / COMMAND_LOG_RELATIVE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command,
        "actor": ctx.actor,
        "source": ctx.source,
        "target_artifact": target_artifact,
        "input_payload": input_payload,
        "output_summary": output_summary,
        "changed_files": changed_files,
        "errors": errors,
        "approval_status": approval_status,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def _emit(payload: dict[str, object], json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, sort_keys=True))
        return
    print(payload.get("summary") or payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Conductor command layer for structured Worklog operations.")
    parser.add_argument("--worklog-root", default=str(DEFAULT_WORKLOG_ROOT))
    parser.add_argument("--actor", default=os.environ.get("CONDUCTOR_ACTOR", "david"))
    parser.add_argument("--source", default=os.environ.get("CONDUCTOR_SOURCE", "cli"))
    parser.add_argument("--json", action="store_true", dest="json_mode")
    subparsers = parser.add_subparsers(dest="command", required=True)

    brief = subparsers.add_parser("brief", help="Generate a structured brief packet.")
    brief_sub = brief.add_subparsers(dest="brief_command", required=True)
    brief_current = brief_sub.add_parser("current", help="Brief the current Worklog state.")
    brief_sprint = brief_sub.add_parser("sprint", help="Brief a sprint by sprint code.")
    brief_sprint.add_argument("sprint_code")

    report = subparsers.add_parser("report", help="Generate a structured report packet.")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    report_today = report_sub.add_parser("today", help="Report today's current state.")

    shortcode = subparsers.add_parser("shortcode", help="Resolve a shortcode and write a result artifact.")
    shortcode_sub = shortcode.add_subparsers(dest="shortcode_command", required=True)
    shortcode_resolve = shortcode_sub.add_parser("resolve", help="Resolve a shortcode to a result artifact.")
    shortcode_resolve.add_argument("shortcode")
    shortcode_resolve.add_argument("--result", default="RESULT_SHORTCODE")
    shortcode_resolve.add_argument("--request-id", default="")

    work_order = subparsers.add_parser("work-order", help="Inspect or route a Worklog work order.")
    work_order_sub = work_order.add_subparsers(dest="work_order_command", required=True)
    work_order_fu = work_order_sub.add_parser("fu", help="Route a work-order follow-up.")
    work_order_fu.add_argument("work_order_id")
    work_order_issue = work_order_sub.add_parser("issue", help="Issue a new work order transactionally.")
    work_order_issue.add_argument("work_order_id")
    work_order_issue.add_argument("--title", required=True)
    work_order_issue.add_argument("--objective", required=True)

    sprint = subparsers.add_parser("sprint", help="Inspect or repair sprint records.")
    sprint_sub = sprint.add_subparsers(dest="sprint_command", required=True)
    sprint_repair = sprint_sub.add_parser("repair-followups", help="Seed missing follow-ups for active sprints.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _resolve_root(args.worklog_root)
    ctx = CommandContext(worklog_root=root, actor=args.actor, source=args.source)

    try:
        if args.command == "brief" and args.brief_command == "current":
            payload = _brief_current(root)
            payload["summary"] = "Brief packet for current Worklog state"
            _log_command(ctx, "brief current", "00-dashboard/current-focus.md", {}, "brief packet generated", [], [])
            _emit(payload, args.json_mode)
            return 0
        if args.command == "brief" and args.brief_command == "sprint":
            payload = _brief_sprint(root, args.sprint_code)
            payload["summary"] = f"Brief packet for sprint {args.sprint_code}"
            _log_command(ctx, f"brief sprint {args.sprint_code}", payload["current_context"]["artifact"], {"sprint_code": args.sprint_code}, "brief packet generated", [], [])
            _emit(payload, args.json_mode)
            return 0
        if args.command == "report" and args.report_command == "today":
            payload = _report_today(root)
            payload["summary"] = "Report packet for today"
            _log_command(ctx, "report today", "03-active-work", {}, "report packet generated", [], [])
            _emit(payload, args.json_mode)
            return 0
        if args.command == "shortcode" and args.shortcode_command == "resolve":
            request = _find_request_by_shortcode(root, args.shortcode)
            if not request and args.request_id:
                for candidate in _request_files(root):
                    record = _parse_shortcode_request(candidate)
                    if record["request_id"].strip().lower() == args.request_id.strip().lower():
                        request = record
                        break
            result_path = _write_shortcode_result(root, args.shortcode, request, args.result)
            payload = {
                "summary": f"Shortcode {args.shortcode} resolved",
                "current_context": {
                    "shortcode": args.shortcode,
                    "request": request["path"] if request else None,
                    "result_path": str(result_path),
                },
                "status": {
                    "resolved": request is not None,
                },
                "what_changed": [
                    f"Wrote shortcode result artifact at {result_path.relative_to(root)}",
                ],
                "open_decisions": [],
                "risks": [],
                "next_recommended_actions": [],
                "exact_question_for_chatgpt": f"What should Conductor do with shortcode {args.shortcode} next?",
            }
            _log_command(
                ctx,
                f"shortcode resolve {args.shortcode}",
                str(result_path.relative_to(root)),
                {"shortcode": args.shortcode, "result": args.result, "request_id": args.request_id},
                "shortcode result artifact generated",
                [str(result_path.relative_to(root))],
                [],
            )
            _emit(payload, args.json_mode)
            return 0
        if args.command == "work-order" and args.work_order_command == "fu":
            work_order = _find_work_order(root, args.work_order_id)
            if not work_order:
                raise FileNotFoundError(f"Work order not found: {args.work_order_id}")
            work_order = _advance_completed_follow_up(work_order)
            pending = list(work_order.get("pending_follow_ups") or [])
            if len(pending) == 1:
                outcome = "auto_executed"
                summary = f"Work order {args.work_order_id} routed automatically"
                next_actions = [f"Execute pending follow-up: {pending[0]}"]
            elif len(pending) > 1:
                outcome = "multiple_pending"
                summary = f"Work order {args.work_order_id} has multiple pending follow-ups"
                next_actions = pending
            else:
                outcome = "complete"
                summary = f"Work order {args.work_order_id} has no pending follow-ups"
                next_actions = []
            payload = {
                "summary": summary,
                "current_context": {
                    "work_order_id": args.work_order_id,
                    "work_order_path": work_order["path"],
                },
                "status": {
                    "follow_up_count": len(pending),
                    "outcome": outcome,
                },
                "what_changed": [],
                "open_decisions": [],
                "risks": [],
                "next_recommended_actions": next_actions,
                "exact_question_for_chatgpt": f"What should Conductor do with work order {args.work_order_id} next?",
            }
            _log_command(
                ctx,
                f"work-order fu {args.work_order_id}",
                str(work_order["path"]),
                {"work_order_id": args.work_order_id},
                summary,
                [],
                [],
            )
            _emit(payload, args.json_mode)
            return 0
        if args.command == "work-order" and args.work_order_command == "issue":
            result = issue_work_order(root, args.work_order_id, args.title, args.objective)
            payload = {
                "summary": f"Work order {args.work_order_id} issued",
                "current_context": result,
                "status": {
                    "issued": True,
                },
                "what_changed": [
                    f"Created {result['issue_path']}",
                    f"Created {result['work_order_path']}",
                ],
                "open_decisions": [],
                "risks": [],
                "next_recommended_actions": [],
                "exact_question_for_chatgpt": f"What should Conductor do with work order {args.work_order_id} next?",
            }
            _log_command(
                ctx,
                f"work-order issue {args.work_order_id}",
                result["work_order_path"],
                {"work_order_id": args.work_order_id, "title": args.title, "objective": args.objective},
                "work order issued transactionally",
                [result["issue_path"], result["work_order_path"]],
                [],
            )
            _emit(payload, args.json_mode)
            return 0
        if args.command == "sprint" and args.sprint_command == "repair-followups":
            repaired: list[str] = []
            for path in _active_sprint_files(root):
                sprint_record = _parse_sprint_record(path)
                if _seed_follow_up_from_sprint(root, sprint_record):
                    repaired.append(str(sprint_record.get("sprint_code") or path.stem))
            payload = {
                "summary": "Active sprint follow-up repair complete",
                "current_context": {
                    "repaired": repaired,
                },
                "status": {
                    "repaired_count": len(repaired),
                },
                "what_changed": [
                    f"Seeded follow-up work orders for {len(repaired)} active sprint(s).",
                ],
                "open_decisions": [],
                "risks": [],
                "next_recommended_actions": [],
                "exact_question_for_chatgpt": "What should Conductor do next after repairing active sprint follow-ups?",
            }
            _log_command(
                ctx,
                "sprint repair-followups",
                None,
                {},
                "active sprint follow-up repair complete",
                [],
                [],
            )
            _emit(payload, args.json_mode)
            return 0
        parser.error(f"Unsupported command: {args.command}")
    except FileNotFoundError as exc:
        error_payload = {"error": str(exc)}
        _log_command(ctx, " ".join(sys.argv[1:]), None, {}, "", [], [str(exc)])
        if args.json_mode:
            print(json.dumps(error_payload, sort_keys=True), file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
