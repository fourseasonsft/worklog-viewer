from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as viewer_app


class WorklogAssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.kb_root = self.root / "fsft-knowledge-base"
        self._make_worklog()
        self._make_kb()
        self.old_root = viewer_app.WORKLOG_ROOT
        self.old_thought = viewer_app.THOUGHT_BOX_DIR
        self.old_handoffs = viewer_app.SPRINT_HANDOFFS_DIR
        viewer_app.WORKLOG_ROOT = self.root
        viewer_app.THOUGHT_BOX_DIR = self.root / "04-inbox/thought-box"
        viewer_app.SPRINT_HANDOFFS_DIR = self.root / "05-sprint-handoffs"
        viewer_app.app.config["OPENAI_API_KEY"] = ""

    def tearDown(self) -> None:
        viewer_app.WORKLOG_ROOT = self.old_root
        viewer_app.THOUGHT_BOX_DIR = self.old_thought
        viewer_app.SPRINT_HANDOFFS_DIR = self.old_handoffs
        self.tmp.cleanup()

    def _make_worklog(self) -> None:
        for rel in [
            "00-dashboard",
            "01-daily-logs/2026/06",
            "03-active-work",
            "04-inbox/new",
            "04-inbox/bugs",
            "04-inbox/features",
            "04-inbox/support",
            "04-inbox/thought-box",
            "04-inbox/thought-box/digested",
            "04-inbox/thought-box/archived",
            "05-release-notes/assistant-update-shipments",
            "05-sprint-handoffs",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "00-dashboard/current-focus.md").write_text("# Current Focus\n\n- Keep the day simple.\n", encoding="utf-8")
        (self.root / "00-dashboard/next-actions.md").write_text("# Next Actions\n\n- Finish intake.\n", encoding="utf-8")
        (self.root / "00-dashboard/where-we-left-off.md").write_text("# Where We Left Off\n\n- Ready.\n", encoding="utf-8")
        (self.root / "03-active-work/worklog.md").write_text("# Worklog Active Work\n", encoding="utf-8")
        (self.root / "03-active-work/ims.md").write_text("# IMS Active Work\n", encoding="utf-8")
        (self.root / "03-active-work/dispatch.md").write_text("# Dispatch Active Work\n", encoding="utf-8")
        (self.root / "03-active-work/cy-storage.md").write_text("# CY Storage Active Work\n", encoding="utf-8")

    def _make_kb(self) -> None:
        (self.kb_root / "07-worklog").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "03-ims").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "05-dispatch").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "04-cy-storage").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "01-core").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "02-unity").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "20-xalan").mkdir(parents=True, exist_ok=True)
        (self.kb_root / "07-worklog/index.md").write_text("# Worklog\n", encoding="utf-8")
        (self.kb_root / "07-worklog/worklog-overview.md").write_text("# Overview\n", encoding="utf-8")
        (self.kb_root / "07-worklog/worklog-viewer.md").write_text("# Viewer\n", encoding="utf-8")
        (self.kb_root / "03-ims/index.md").write_text("# IMS\n", encoding="utf-8")
        (self.kb_root / "05-dispatch/index.md").write_text("# Dispatch\n", encoding="utf-8")
        (self.kb_root / "04-cy-storage/index.md").write_text("# CY Storage\n", encoding="utf-8")
        (self.kb_root / "01-core/index.md").write_text("# Core\n", encoding="utf-8")
        (self.kb_root / "02-unity/index.md").write_text("# Unity\n", encoding="utf-8")
        (self.kb_root / "20-xalan/index.md").write_text("# Xalan\n", encoding="utf-8")

    def _client(self):
        client = viewer_app.app.test_client()
        with client.session_transaction() as sess:
            sess[viewer_app.WORKLOG_SESSION_KEY] = {
                "core_user_id": "1",
                "username": "david",
                "email": "david@example.com",
                "roles": ["Super Admin"],
                "permissions": ["*"],
                "application_keys": ["worklog"],
                "portal_keys": [],
                "authenticated_at": 0,
                "expires_at": 9999999999,
            }
        return client

    def _write_thought(self, name: str, body: str) -> Path:
        path = self.root / "04-inbox/thought-box" / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_assistant_renders(self) -> None:
        response = self._client().get("/assistant")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Idea Inventory digest to sprint groups", html)
        self.assertIn("Active Idea Inventory", html)
        self.assertIn("digest-grouping-review-modal", html)
        self.assertIn("data-thought-path", html)
        self.assertNotIn("Digest by App/Product", html)
        self.assertNotIn("Proposed Sprint Groups", html)
        self.assertNotIn("Approved Sprint Queue", html)
        self.assertIn("Digest Selected", html)
        self.assertIn("select-all-ideas", html)
        self.assertNotIn("Inventory Actions", html)

    def test_message_stores_raw_idea(self) -> None:
        response = self._client().post(
            "/api/assistant/message",
            json={"message": "hey for IMS we need to do x, y, z"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn("thought_path", body)
        thought_files = list((self.root / "04-inbox/thought-box").glob("*.md"))
        self.assertEqual(len(thought_files), 1)
        content = thought_files[0].read_text(encoding="utf-8")
        self.assertIn("- status: raw", content)
        self.assertIn("- digest_status: not_digested", content)

    def test_save_idea_reloads_inventory(self) -> None:
        response = self._client().post(
            "/api/assistant/message",
            json={"message": "Worklog needs calmer inbox rows"},
        )
        self.assertEqual(response.status_code, 200)
        html = self._client().get("/assistant").get_data(as_text=True)
        self.assertIn("Worklog needs calmer inbox rows", html)
        self.assertIn("idea-select", html)

    def test_inventory_table_uses_short_display_fields(self) -> None:
        thought = self._write_thought(
            "2026-06-20-100000-clean.md",
            "# Clean Thought\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: 2026-06-20 10:00 Please tighten the IMS table.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: Please tighten the IMS table.\n",
        )
        item = viewer_app._thought_box_items(digested_only=False)[0]
        self.assertRegex(item["created_display"], r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}")
        self.assertNotIn("2026-06-20 10:00", item["display_snippet"])
        self.assertEqual(item["raw_text_full"], "2026-06-20 10:00 Please tighten the IMS table.")

    def test_thought_parser_reads_full_raw_text_and_normalizes_summary(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-filter.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: 2026 06 20 174635 On Worklog Inbox Sprint Queue Filters Should N\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Inbox filters.\n\n## Raw Thought\n2026 06 20 174635 On Worklog Inbox Sprint Queue Filters Should N\nselecting the filter should auto apply we only need a clear filter b\n",
        )
        item = viewer_app._thought_box_items(digested_only=False)[0]
        self.assertEqual(item["raw_text_full"], "2026 06 20 174635 On Worklog Inbox Sprint Queue Filters Should N\nselecting the filter should auto apply we only need a clear filter b")
        self.assertEqual(item["normalized_summary"], "Inbox and Sprint Queue filters should auto-apply when changed.")
        self.assertIn("selecting the filter should auto apply", item["display_snippet"])

    def test_digest_preview_does_not_move_files(self) -> None:
        thought = self._write_thought(
            "2026-06-20-100000-ims-break-bulk.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling and a box-quantity UI update.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        before = sorted(p.name for p in (self.root / "04-inbox/thought-box").glob("*.md"))
        response = self._client().get("/assistant?digest_preview=1")
        after = sorted(p.name for p in (self.root / "04-inbox/thought-box").glob("*.md"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        self.assertTrue(thought.exists())
        html = response.get_data(as_text=True)
        self.assertIn("Digest Grouping Review", html)

    def test_digest_selected_only_includes_selected_ideas(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        preview = self._client().post(
            "/api/assistant/digest-preview",
            json={
                "selected_idea_ids": [viewer_app._thought_box_items(digested_only=False)[0]["thought_id"]],
                "selected_only": True,
            },
        ).get_json()["digest_preview"]
        self.assertEqual(preview["selection_mode"], "selected")
        selected_item = next(item for item in viewer_app._thought_box_items(digested_only=False) if item["thought_id"] == preview["selected_thought_ids"][0])
        self.assertEqual(preview["selected_thought_ids"], [selected_item["thought_id"]])
        self.assertEqual(preview["selected_idea_ids"], [selected_item["thought_id"]])
        self.assertEqual(preview["source_thought_paths"], [selected_item["path"]])
        self.assertEqual(len(preview["active_items"]), 1)

    def test_digest_preview_returns_selected_payload_fields(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs queue selection.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs queue selection.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        preview = self._client().post(
            "/api/assistant/digest-preview",
            json={
                "selected_idea_ids": [item["thought_id"] for item in viewer_app._thought_box_items(digested_only=False)],
                "selected_only": True,
            },
        ).get_json()["digest_preview"]
        self.assertEqual(preview["selected_idea_count"], 2)
        self.assertEqual(len(preview["selected_thought_ids"]), 2)
        self.assertEqual(len(preview["source_thought_paths"]), 2)

    def test_digest_all_includes_all_active_ideas(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={"selected_only": False, "thought_paths": []}).get_json()["digest_preview"]
        self.assertEqual(len(preview["active_items"]), 2)

    def test_digest_groups_by_app_and_sprint_group(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling and better table labels.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        self._write_thought(
            "2026-06-20-100001-ims-2.md",
            "# IMS 2\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs better table labels and status cards.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs better table labels.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        self.assertIn("sprint_groups", preview)
        self.assertTrue(any(group["app_product"] == "IMS" for group in preview["sprint_groups"]))
        self.assertTrue(all(group.get("sprint_code") for group in preview["sprint_groups"]))

    def test_worklog_keywords_classify_as_worklog(self) -> None:
        inferred = viewer_app._infer_thought("Worklog idea inventory sprint queue handoff dashboard cleanup")
        self.assertEqual(inferred["ai_inferred_app"], "Worklog")

    def test_worklog_sprint_groups_get_specific_names_and_purpose(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-ui.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Make idea rows click to select. Use short date and PST time on ideas inventory date/time column. I don't want to see inbox/new/bugs/features/support/closed on the menu.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog UI cleanup.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        group = next(item for item in preview["sprint_groups"] if item["app_product"] == "Worklog")
        self.assertNotIn("Other", group["sprint_group_name"])
        self.assertIn("Worklog", group["sprint_group_name"])
        self.assertEqual(
            group["purpose"],
            "Clean up the Worklog Idea Inventory and navigation experience by improving row selection, date formatting, and menu simplicity.",
        )

    def test_digest_output_renders_as_tables(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-ui.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog should have a calmer dashboard table.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog should have a calmer dashboard table.\n",
        )
        html = self._client().get("/assistant?digest_preview=1").get_data(as_text=True)
        self.assertIn("<table", html)
        self.assertIn("digest-grouping-review-modal", html)
        self.assertIn("review suggested sprint groups before creating proposals", html.lower())
        self.assertNotIn("new bootstrap.Modal", html)

    def test_create_proposed_sprints_from_suggested_groups(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        self._write_thought(
            "2026-06-20-100001-ims-2.md",
            "# IMS 2\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs a box-quantity sprint group.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs a box-quantity sprint group.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["created_proposed_sprints"])
        self.assertTrue(body["assistant_reply"].startswith("Proposed sprint groups created"))
        proposed_files = list((self.root / "06-sprints/proposed").glob("*.md"))
        self.assertTrue(proposed_files)
        proposed_text = proposed_files[0].read_text(encoding="utf-8")
        self.assertIn("## Source Ideas", proposed_text)
        self.assertIn("## Proposed Work", proposed_text)
        self.assertIn("## Codex/ChatGPT Starting Prompt", proposed_text)
        self.assertTrue(list((self.root / "04-inbox/thought-box/digested").glob("*.md")))

    def test_create_proposed_sprints_only_moves_selected_thoughts(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        preview = self._client().post(
            "/api/assistant/digest-preview",
            json={
                "thought_ids": [viewer_app._thought_box_items(digested_only=False)[0]["thought_id"]],
                "selected_only": True,
            },
        ).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        digested = sorted(p.name for p in (self.root / "04-inbox/thought-box/digested").glob("*.md"))
        active = sorted(p.name for p in (self.root / "04-inbox/thought-box").glob("*.md"))
        self.assertEqual(len(digested), 1)
        self.assertEqual(len(active), 1)
        self.assertIn("2026-06-20-100000-ims.md", active[0])

    def test_empty_selection_returns_clear_error(self) -> None:
        response = self._client().post(
            "/api/assistant/digest-preview",
            json={"selected_idea_ids": [], "selected_only": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Select at least one raw idea", response.get_json()["error"])

    def test_invalid_selection_returns_clear_error(self) -> None:
        response = self._client().post(
            "/api/assistant/digest-preview",
            json={"selected_idea_ids": ["missing-id"], "selected_only": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer match active raw ideas", response.get_json()["error"])

    def test_digest_preview_does_not_create_proposed_records(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        response = self._client().post("/api/assistant/digest-preview", json={})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["digest_preview"]["review_mode"])
        self.assertFalse(list((self.root / "06-sprints/proposed").glob("*.md")))

    def test_digest_message_uses_review_workflow(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        response = self._client().post("/api/assistant/message", json={"message": "digest my thought box"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["digest_preview"]["review_mode"])
        self.assertIn("Digest Grouping Review ready", body["assistant_reply"])

    def test_cancel_creates_no_proposed_records(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "cancel"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(list((self.root / "06-sprints/proposed").glob("*.md")))

    def test_combine_all_creates_one_proposed_record_with_all_ideas(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog-2.md",
            "# Worklog 2\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer dashboard.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer dashboard.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "combine_all"})
        self.assertEqual(response.status_code, 200)
        proposed_files = list((self.root / "06-sprints/proposed").glob("*.md"))
        self.assertEqual(len(proposed_files), 1)
        self.assertIn("Worklog", proposed_files[0].read_text(encoding="utf-8"))

    def test_create_proposed_sprints_without_groups_fails_safely(self) -> None:
        response = self._client().post(
            "/api/assistant/create-proposed-sprints",
            json={"digest_preview": {"sprint_groups": []}, "action": "accept_suggested"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("No suggested groups were available", response.get_json()["error"])

    def test_selected_digest_flow_creates_sprint_record_and_preserves_others(self) -> None:
        self._write_thought(
            "2026-06-20-100000-ims.md",
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
        )
        self._write_thought(
            "2026-06-20-100002-dispatch.md",
            "# Dispatch\n\n- created_at: 2026-06-20T10:00:02Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Dispatch needs a load board cleanup.\n- ai_inferred_app: Dispatch\n- ai_inferred_type: feature\n- ai_summary: Dispatch needs a load board cleanup.\n",
        )
        selected = next(item for item in viewer_app._thought_box_items(digested_only=False) if item["path"].endswith("100000-ims.md"))
        preview = self._client().post(
            "/api/assistant/digest-preview",
            json={"selected_idea_ids": [selected["thought_id"]], "selected_only": True},
        ).get_json()["digest_preview"]
        self.assertEqual(preview["source_thought_paths"], [selected["path"]])
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["created_proposed_sprints"])
        self.assertTrue(body["sprint_queue_url"].endswith("/sprints?status=proposed"))
        proposed_files = list((self.root / "06-sprints/proposed").glob("*.md"))
        self.assertEqual(len(proposed_files), 1)
        digested_files = sorted(p.name for p in (self.root / "04-inbox/thought-box/digested").glob("*.md"))
        active_files = sorted(p.name for p in (self.root / "04-inbox/thought-box").glob("*.md"))
        self.assertEqual(len(digested_files), 1)
        self.assertEqual(len(active_files), 2)
        self.assertIn("2026-06-20-100001-worklog.md", active_files)
        self.assertIn("2026-06-20-100002-dispatch.md", active_files)
        self.assertTrue(any("Sprint Code" in path.read_text(encoding="utf-8") for path in proposed_files))
        queue_html = self._client().get("/sprints?status=proposed").get_data(as_text=True)
        self.assertIn("proposed", queue_html.lower())
        self.assertTrue(body["assistant_reply"].startswith("Proposed sprint groups created"))
        detail_html = self._client().get(body["sprint_detail_urls"][0]).get_data(as_text=True)
        self.assertIn("Sprint Code", detail_html)
        self.assertIn("Source Ideas", detail_html)
        self.assertIn("Proposed Work", detail_html)
        self.assertIn("Completion Requirement", detail_html)
        self.assertIn("Codex Prompt", detail_html)
        proposed_text = proposed_files[0].read_text(encoding="utf-8")
        self.assertIn("# Sprint Handoff:", proposed_text)
        self.assertIn("## Source Ideas", proposed_text)
        self.assertIn("## Proposed Work", proposed_text)
        self.assertIn("## Codex/ChatGPT Starting Prompt", proposed_text)

    def test_handoff_uses_normalized_summaries_and_full_proposed_work(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: On Worklog I want to get rid of all the inbox / new /bugs / features / support / closed\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Inbox navigation.\n",
        )
        self._write_thought(
            "2026-06-20-100001-worklog-idea.md",
            "# Worklog 2\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: For Worklog Active idea inventory area, Created should be short date and short time in PST. Raw thought doesn't need date / time.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Idea inventory readability.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        proposal_file = next(path for path in (self.root / "06-sprints/proposed").glob("*.md") if "# Proposed Sprint Group:" in path.read_text(encoding="utf-8"))
        text = proposal_file.read_text(encoding="utf-8")
        self.assertIn("## Source Ideas", text)
        self.assertIn("## Proposed Work", text)
        self.assertIn("Purpose", text)
        self.assertIn("Completion Requirement", text)

    def test_codex_prompt_uses_clean_summaries(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: 2026 06 20 174635 On Worklog Inbox Sprint Queue Filters Should N\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Inbox filters.\n\n## Raw Thought\n2026 06 20 174635 On Worklog Inbox Sprint Queue Filters Should N\nselecting the filter should auto apply we only need a clear filter b\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        prompt = preview["sprint_groups"][0]["starting_prompt"]
        self.assertIn("Sprint Code:", prompt)
        self.assertIn("Purpose:", prompt)
        self.assertIn("Inbox and Sprint Queue filters should auto-apply when changed.", prompt)
        self.assertNotIn("2026 06 20 174635", prompt)
        self.assertNotIn("worklog-100000", prompt.lower())

    def test_handoff_includes_source_ideas_and_prompt(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer inbox queue.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer inbox queue.\n",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        proposal_file = next(path for path in (self.root / "06-sprints/proposed").glob("*.md") if "# Proposed Sprint Group:" in path.read_text(encoding="utf-8"))
        text = proposal_file.read_text(encoding="utf-8")
        self.assertIn("Source Ideas", text)
        self.assertIn("Codex/ChatGPT Starting Prompt", text)
        self.assertIn("Completion Requirement", text)
        self.assertIn("Sprint Code:", text)

    def test_no_thoughts_empty_state_works(self) -> None:
        html = self._client().get("/assistant").get_data(as_text=True)
        self.assertIn("No active raw ideas yet.", html)


if __name__ == "__main__":
    unittest.main()
