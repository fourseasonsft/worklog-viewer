#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import app as viewer_app


def _build_preview(args: argparse.Namespace) -> dict[str, object]:
    thoughts = []
    for index, idea in enumerate(args.source_idea):
        text = idea.strip()
        if not text:
            continue
        thoughts.append(
            {
                "path": f"cli-source-{index + 1}.md",
                "title": text[:80] or "Source Idea",
                "raw_text_full": text,
                "raw_text": text,
                "normalized_summary": text,
                "display_snippet": text,
            }
        )
    if not thoughts:
        raise ValueError("At least one non-empty --source-idea is required.")

    app_product = args.app.strip()
    scope = (args.scope or viewer_app._sprint_group_scope(thoughts)).strip() or "Small"
    sprint_group_name = args.title.strip()
    purpose = (args.purpose or "").strip()
    recommended_first_step = (args.recommended_first_step or "").strip()
    group = {
        "app_product": app_product,
        "sprint_group_name": sprint_group_name,
        "ideas_included": len(thoughts),
        "proposed_type": viewer_app._sprint_group_type(thoughts),
        "feasibility": viewer_app._sprint_group_feasibility(thoughts),
        "suggested_priority": args.priority or viewer_app._sprint_group_priority(thoughts),
        "recommended_first_step": recommended_first_step or thoughts[0]["normalized_summary"],
        "source_thoughts": [thought["path"] for thought in thoughts],
        "scope": scope,
        "purpose": purpose or f"Turn {app_product} ideas into a focused sprint.",
        "starting_prompt": "",
        "thoughts": thoughts,
    }
    return {
        "plain_summary": f"{len(thoughts)} source idea(s) prepared for sprint creation.",
        "sprint_groups": [group],
        "combined_app_product": app_product,
        "combined_sprint_group_name": sprint_group_name,
        "source_thoughts": [thought["path"] for thought in thoughts],
        "source_idea_summaries": [thought["normalized_summary"] for thought in thoughts],
        "source_thought_paths": [thought["path"] for thought in thoughts],
        "source_thought_ids": [thought["path"] for thought in thoughts],
    }


def _resolve_duplicate_result(created: list[dict[str, object]]) -> dict[str, object] | None:
    if not created:
        return None
    record = created[0]
    if record.get("_existing_duplicate"):
        return record
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a proposed Worklog sprint using the canonical builder.")
    parser.add_argument("--app", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--source-idea", action="append", required=True, dest="source_idea")
    parser.add_argument("--scope")
    parser.add_argument("--purpose")
    parser.add_argument("--recommended-first-step")
    parser.add_argument("--priority")
    parser.add_argument("--worklog-root")
    parser.add_argument("--json-output", action="store_true")
    args = parser.parse_args()

    original_root = viewer_app.WORKLOG_ROOT
    original_thought = viewer_app.THOUGHT_BOX_DIR
    original_handoffs = viewer_app.SPRINT_HANDOFFS_DIR
    try:
        if args.worklog_root:
            root = Path(args.worklog_root).resolve()
            viewer_app.WORKLOG_ROOT = root
            viewer_app.THOUGHT_BOX_DIR = root / "04-inbox/thought-box"
            viewer_app.SPRINT_HANDOFFS_DIR = root / "05-sprint-handoffs"

        preview = _build_preview(args)
        created = viewer_app._create_proposed_sprints_from_preview(preview, mode="suggested")
        duplicate = _resolve_duplicate_result(created)
        if duplicate:
            payload = {
                "created": False,
                "duplicate": True,
                "existing_sprint_code": duplicate.get("sprint_code") or duplicate.get("intended_sprint_code") or "",
                "existing_record_path": duplicate.get("path") or "",
            }
            if args.json_output:
                print(json.dumps(payload))
            else:
                print(f"Duplicate sprint already exists: {payload['existing_sprint_code']} ({payload['existing_record_path']})")
            return 0

        sprint = created[0] if created else {}
        payload = {
            "created": True,
            "duplicate": False,
            "sprint_code": sprint.get("sprint_code") or sprint.get("intended_sprint_code") or "",
            "proposal_id": sprint.get("proposal_id") or "",
            "record_path": sprint.get("path") or "",
            "handoff_preview": sprint.get("handoff_md") or "",
        }
        if args.json_output:
            print(json.dumps(payload))
        else:
            print(f"Created sprint {payload['sprint_code']} at {payload['record_path']}")
        return 0
    finally:
        viewer_app.WORKLOG_ROOT = original_root
        viewer_app.THOUGHT_BOX_DIR = original_thought
        viewer_app.SPRINT_HANDOFFS_DIR = original_handoffs


if __name__ == "__main__":
    raise SystemExit(main())
