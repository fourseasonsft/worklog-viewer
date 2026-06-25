#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from validation_session_lib import (
    ALLOWED_FINDING_SEVERITIES,
    ALLOWED_ITEM_STATUSES,
    ALLOWED_SESSION_STATUSES,
    SEED_PROFILE,
    complete_session,
    default_session_payload,
    generate_handoff_markdown,
    read_session,
    seed_profile_or_error,
    seed_session_payload,
    session_path,
    slugify,
    update_item,
    write_session,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Worklog operational validation sessions.")
    parser.add_argument("--worklog-root", default="/opt/fsftdev/fsft-worklog")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a validation session markdown file.")
    create.add_argument("--title", default=seed_session_payload()["title"])
    create.add_argument("--slug")
    create.add_argument("--app", default=seed_session_payload()["app"])
    create.add_argument("--run", default=seed_session_payload()["run"])
    create.add_argument("--track", default=seed_session_payload()["track"])
    create.add_argument("--release", default=seed_session_payload()["release"])
    create.add_argument("--status", default="in_progress", choices=sorted(ALLOWED_SESSION_STATUSES))
    create.add_argument("--seed", choices=[SEED_PROFILE])
    create.add_argument("--json-output", action="store_true")

    update = subparsers.add_parser("update-item", help="Update an item in a validation session.")
    update.add_argument("--session", required=True)
    update.add_argument("--id", required=True)
    update.add_argument("--section")
    update.add_argument("--description")
    update.add_argument("--status", choices=sorted(ALLOWED_ITEM_STATUSES))
    update.add_argument("--notes")
    update.add_argument("--finding-severity", dest="finding_severity", choices=sorted(ALLOWED_FINDING_SEVERITIES))
    update.add_argument("--finding-summary", dest="finding_summary")
    update.add_argument("--json-output", action="store_true")

    handoff = subparsers.add_parser("generate-handoff", help="Generate a handoff from a validation session.")
    handoff.add_argument("--session", required=True)
    handoff.add_argument("--output")
    handoff.add_argument("--json-output", action="store_true")

    complete = subparsers.add_parser("complete", help="Mark a validation session completed.")
    complete.add_argument("--session", required=True)
    complete.add_argument("--json-output", action="store_true")

    return parser


def _resolve_root(raw_root: str) -> Path:
    return Path(raw_root).expanduser().resolve()


def _handle_create(args: argparse.Namespace, root: Path) -> int:
    slug = args.slug.strip() if args.slug else slugify(str(args.title or "Validation Session"))
    path = session_path(root, slug)
    if path.exists():
        raise FileExistsError(path)
    if args.seed:
        data = seed_profile_or_error(args.seed)
        data["slug"] = slug
        data["title"] = str(args.title or data["title"])
        data["app"] = str(args.app or data["app"])
        data["run"] = str(args.run or data["run"])
        data["track"] = str(args.track or data["track"])
        data["release"] = str(args.release or data["release"])
        data["status"] = str(args.status or data["status"])
    else:
        data = default_session_payload(str(args.title), slug, str(args.app), str(args.run), str(args.track), str(args.release), str(args.status))
    write_session(path, data)
    payload = {"created": True, "path": str(path), "slug": slug, "title": data["title"], "status": data["status"]}
    if args.json_output:
        print(json.dumps(payload))
    else:
        print(f"Created validation session at {path}")
    return 0


def _handle_update_item(args: argparse.Namespace, root: Path) -> int:
    path, data = read_session(root, args.session)
    data = update_item(
        data,
        args.id,
        {
            "section": args.section,
            "description": args.description,
            "status": args.status,
            "notes": args.notes,
            "finding_severity": args.finding_severity,
            "finding_summary": args.finding_summary,
        },
    )
    write_session(path, data)
    if args.json_output:
        print(json.dumps({"updated": True, "path": str(path), "item_id": args.id}))
    else:
        print(f"Updated validation session item {args.id} in {path}")
    return 0


def _handle_generate_handoff(args: argparse.Namespace, root: Path) -> int:
    path, data = read_session(root, args.session)
    handoff_base = root / "05-sprint-handoffs" / "validation-sessions"
    handoff_base.mkdir(parents=True, exist_ok=True)
    if args.output:
        output = Path(args.output).expanduser()
        if not output.is_absolute():
            output = (root / output).resolve()
        else:
            output = output.resolve()
    else:
        output = handoff_base / f"{data.get('slug') or slugify(str(data.get('title') or 'validation-session'))}.md"
    handoff_md = generate_handoff_markdown(data, session_path_value=path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(handoff_md, encoding="utf-8")
    data["handoff_path"] = str(output.relative_to(root))
    write_session(path, data)
    payload = {"generated": True, "session": str(path), "handoff_path": str(output)}
    if args.json_output:
        print(json.dumps(payload))
    else:
        print(f"Generated handoff at {output}")
    return 0


def _handle_complete(args: argparse.Namespace, root: Path) -> int:
    path, data = read_session(root, args.session)
    data = complete_session(data)
    write_session(path, data)
    if args.json_output:
        print(json.dumps({"completed": True, "path": str(path)}))
    else:
        print(f"Marked validation session completed at {path}")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = _resolve_root(args.worklog_root)
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
