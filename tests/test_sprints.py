from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as viewer_app


class WorklogSprintQueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_root = viewer_app.WORKLOG_ROOT
        self.old_thought = viewer_app.THOUGHT_BOX_DIR
        self.old_handoffs = viewer_app.SPRINT_HANDOFFS_DIR
        viewer_app.WORKLOG_ROOT = self.root
        viewer_app.THOUGHT_BOX_DIR = self.root / "04-inbox/thought-box"
        viewer_app.SPRINT_HANDOFFS_DIR = self.root / "05-sprint-handoffs"
        self._make_structure()

    def tearDown(self) -> None:
        viewer_app.WORKLOG_ROOT = self.old_root
        viewer_app.THOUGHT_BOX_DIR = self.old_thought
        viewer_app.SPRINT_HANDOFFS_DIR = self.old_handoffs
        self.tmp.cleanup()

    def _make_structure(self) -> None:
        for rel in [
            "00-dashboard",
            "03-active-work",
            "04-inbox/thought-box",
            "04-inbox/thought-box/digested",
            "05-sprint-handoffs",
            "06-sprints/proposed",
            "06-sprints/approved",
            "06-sprints/active",
            "06-sprints/completed",
            "06-sprints/staged",
            "06-sprints/shipped",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        for name in ["core", "unity", "ims", "dispatch", "parking", "cy-storage", "hiring", "worklog"]:
            (self.root / f"03-active-work/{name}.md").write_text(f"# {name.title()} Active Work\n", encoding="utf-8")
        (self.root / "03-active-work/ims.md").write_text(
            "# IMS Active Work\n\n## Current Sprint\n\n- Name: IMS launcher polish\n- Status: Active\n- Percent Complete: 50%\n- Started: 2026-06-20\n- Target: 2026-06-28\n- Notes: Keep it focused.\n",
            encoding="utf-8",
        )
        (self.root / "03-active-work/worklog.md").write_text(
            "# Worklog Active Work\n\n## Last Sprint\n\n- Name: Dashboard visual cleanup\n- Completed: 2026-06-20\n- Outcome: Command center layout landed.\n\n## Next Suggested Sprint\n\n- Name: Queue lifecycle refinement\n- Why: Keep the queue model clean.\n- Suggested First Step: Add sprint filters.\n",
            encoding="utf-8",
        )
        for name in ["ims-ui.md", "worklog-queue.md"]:
            (self.root / "04-inbox/thought-box" / name).write_text(
                f"# {name}\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: {name} needs a focused sprint slice.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: {name} needs a focused sprint slice.\n",
                encoding="utf-8",
            )

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

    def _create_sprint_record(self, status: str, app_product: str = "IMS", title: str = "IMS Sprint") -> Path:
        sprint_code = f"{viewer_app._sprint_code_prefix(app_product)}-SPRINT-20260620-001"
        path = self.root / f"06-sprints/{status}/sp-20260620120000-{status}-{title.lower().replace(' ', '-')}.md"
        path.write_text(
            "\n".join(
                [
                    f"# Sprint Queue Record: {title}",
                    "",
                    f"- sprint_id: sp-20260620120000-{status}",
                    f"- sprint_code: {sprint_code}",
                    f"- app_product: {app_product}",
                    f"- status: {status}",
                    "- scope: Small",
                    "- idea_count: 2",
                    "- created_at: 2026-06-20T12:00:00Z",
                    "- updated_at: 2026-06-20T12:30:00Z",
                    "- handoff_path: 05-sprint-handoffs/2026-06-20-120000-ims-sprint.md",
                    "",
                    "## Source Ideas",
                    "- 04-inbox/thought-box/ims-ui.md",
                    "- 04-inbox/thought-box/worklog-queue.md",
                    "",
                    "## Proposed Work",
                    "- Improve the IMS queue surface.",
                    "- Tighten Worklog queue filtering.",
                    "",
                    "## Handoff Markdown",
                    "05-sprint-handoffs/2026-06-20-120000-ims-sprint.md",
                    "",
                    "## Codex/ChatGPT Starting Prompt",
                    f"Sprint Code: {sprint_code}\nCompletion Requirement: Mark work Completed when implementation is finished but not yet deployed. Mark it Staged when deployed to DEV or staging and ready for validation. Mark it Shipped when deployed to production or live. Update the matching Sprint Queue record by Sprint Code and do not leave the sprint status stale.\nStart a focused implementation conversation.",
                    "",
                    "## Completion Requirement",
                    f"When implementation is finished but not deployed, mark the sprint Completed. When deployed to DEV or staging and ready for validation, mark the sprint Staged. When deployed to production or live, mark the sprint Shipped. Update Worklog using Sprint Code {sprint_code}.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (self.root / "05-sprint-handoffs").mkdir(parents=True, exist_ok=True)
        (self.root / "05-sprint-handoffs/2026-06-20-120000-ims-sprint.md").write_text(
            "# Sprint Handoff: IMS Sprint\n\n## App/Product\nIMS\n",
            encoding="utf-8",
        )
        return path

    def _create_proposed_sprint_record(self, title: str = "IMS Proposed", app_product: str = "IMS") -> Path:
        sprint_code = f"{viewer_app._sprint_code_prefix(app_product)}-SPRINT-20260620-001"
        (self.root / "04-inbox/thought-box/ims-ui.md").write_text(
            "# IMS UI\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Improve the IMS queue surface.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: Improve the IMS queue surface.\n",
            encoding="utf-8",
        )
        (self.root / "04-inbox/thought-box/worklog-queue.md").write_text(
            "# Worklog Queue\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Tighten Worklog queue filtering.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Tighten Worklog queue filtering.\n",
            encoding="utf-8",
        )
        path = self.root / f"06-sprints/proposed/pr-20260620120000-{title.lower().replace(' ', '-')}.md"
        path.write_text(
            "\n".join(
                [
                    f"# Proposed Sprint Group: {title}",
                    "",
                    "- proposal_id: pr-20260620120000-001",
                    f"- sprint_group_name: {title}",
                    f"- app_product: {app_product}",
                    "- scope: Small",
                    "- status: proposed",
                    "- created_at: 2026-06-20T12:00:00Z",
                    "- updated_at: 2026-06-20T12:30:00Z",
                    "- source_thought_ids: thought-1, thought-2",
                    "- source_thought_paths: 04-inbox/thought-box/ims-ui.md, 04-inbox/thought-box/worklog-queue.md",
                    "",
                    "## Source Ideas",
                    "- Improve the IMS queue surface.",
                    "- Tighten Worklog queue filtering.",
                    "",
                    "## Proposed Work",
                    "- Improve the IMS queue surface.",
                    "- Tighten Worklog queue filtering.",
                    "",
                    "## Recommended First Step",
                    "Review the source ideas.",
                    "",
                    "## Handoff Preview",
                    "# Sprint Handoff Preview",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def test_sprint_queue_page_renders(self) -> None:
        self._create_sprint_record("approved")
        html = self._client().get("/sprints").get_data(as_text=True)
        self.assertIn("Sprint Queue", html)
        self.assertIn("Sprint Code", html)
        self.assertIn("IMS Sprint", html)
        self.assertIn("Start Sprint", html)
        self.assertIn("onchange=\"this.form.requestSubmit()\"", html)

    def test_proposed_filter_renders_proposed_rows(self) -> None:
        self._create_proposed_sprint_record()
        html = self._client().get("/sprints?status=proposed").get_data(as_text=True)
        self.assertIn("IMS Proposed", html)
        self.assertIn("Approve", html)
        self.assertIn("Reject", html)

    def test_proposed_detail_renders_sprint_style_layout(self) -> None:
        self._create_proposed_sprint_record(title="Worklog Idea Inventory UI Cleanup", app_product="Worklog")
        record = viewer_app._sprint_records()[0]
        html = self._client().get(f"/sprints/{record['id']}").get_data(as_text=True)
        self.assertIn("Summary", html)
        self.assertIn("Sprint Code", html)
        self.assertIn("App/Product", html)
        self.assertIn("Source Ideas", html)
        self.assertIn("Proposed Work", html)
        self.assertIn("Handoff Preview", html)
        self.assertIn("Approve", html)
        self.assertIn("Reject", html)
        self.assertIn("Back to Sprint Queue", html)
        self.assertIn("<details", html)
        self.assertIn("Debug metadata", html)
        self.assertIn("Handoff Preview", html.split("Debug metadata")[0])

    def test_missing_handoff_shows_warning(self) -> None:
        path = self._create_sprint_record("approved")
        (self.root / "05-sprint-handoffs/2026-06-20-120000-ims-sprint.md").unlink()
        text = path.read_text(encoding="utf-8").replace("- handoff_path: 05-sprint-handoffs/2026-06-20-120000-ims-sprint.md\n", "- handoff_path: \n")
        text = text.replace("## Handoff Markdown\n05-sprint-handoffs/2026-06-20-120000-ims-sprint.md\n", "## Handoff Markdown\n\n")
        path.write_text(text, encoding="utf-8")
        html = self._client().get("/sprints/sp-20260620120000-approved").get_data(as_text=True)
        self.assertIn("No handoff content found. Regenerate handoff.", html)
        self.assertIn("Regenerate Handoff", html)

    def test_generated_sprint_code_is_unique(self) -> None:
        self._create_sprint_record("approved", app_product="IMS", title="IMS Sprint 1")
        code = viewer_app._generate_sprint_code("IMS")
        self.assertNotEqual(code, "IMS-SPRINT-20260620-001")
        self.assertRegex(code, r"^IMS-SPRINT-\d{8}-\d{3}$")

    def test_filters_work(self) -> None:
        self._create_sprint_record("approved")
        self._create_sprint_record("shipped", title="Worklog Sprint", app_product="Worklog")
        self._create_sprint_record("staged", title="Worklog Staged", app_product="Worklog")
        client = self._client()
        approved_html = client.get("/sprints?status=approved").get_data(as_text=True)
        self.assertIn("IMS Sprint", approved_html)
        self.assertNotIn("Worklog Sprint", approved_html)
        shipped_html = client.get("/sprints?status=shipped").get_data(as_text=True)
        self.assertIn("Worklog Sprint", shipped_html)
        self.assertNotIn("IMS Sprint", shipped_html)
        staged_html = client.get("/sprints?status=staged").get_data(as_text=True)
        self.assertIn("Worklog Staged", staged_html)
        self.assertNotIn("IMS Sprint", staged_html)
        ims_html = client.get("/sprints?app=ims").get_data(as_text=True)
        self.assertIn("IMS Sprint", ims_html)
        self.assertNotIn("Worklog Sprint", ims_html)
        combo_html = client.get("/sprints?status=approved&app=ims").get_data(as_text=True)
        self.assertIn("IMS Sprint", combo_html)

    def test_detail_page_renders(self) -> None:
        self._create_sprint_record("completed")
        html = self._client().get("/sprints/sp-20260620120000-completed").get_data(as_text=True)
        self.assertIn("Sprint Queue Record", html)
        self.assertIn("Sprint Code", html)
        self.assertIn("Handoff Preview", html)
        self.assertIn("Sprint Handoff: IMS Sprint", html)
        self.assertIn("Copy Prompt", html)
        self.assertIn("Copy Handoff", html)
        self.assertIn("Mark Staged", html)

    def test_transitions_work(self) -> None:
        self._create_sprint_record("approved")
        client = self._client()
        response = client.post("/sprints/sp-20260620120000-approved/action", data={"action": "start"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Active", response.get_data(as_text=True))
        active_path = self.root / "06-sprints/active/sp-20260620120000-approved-ims-sprint.md"
        self.assertTrue(active_path.exists())
        client.post("/sprints/sp-20260620120000-approved/action", data={"action": "complete"}, follow_redirects=True)
        completed_path = self.root / "06-sprints/completed/sp-20260620120000-approved-ims-sprint.md"
        self.assertTrue(completed_path.exists())
        client = self._client()
        response = client.post("/sprints/sp-20260620120000-approved/action", data={"action": "stage"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        staged_path = self.root / "06-sprints/staged/sp-20260620120000-approved-ims-sprint.md"
        self.assertTrue(staged_path.exists())
        client = self._client()
        response = client.post("/sprints/sp-20260620120000-approved/action", data={"action": "ship"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        shipped_path = self.root / "06-sprints/shipped/sp-20260620120000-approved-ims-sprint.md"
        self.assertTrue(shipped_path.exists())

    def test_proposed_approval_moves_to_approved_and_digests_sources(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        response = client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(list((self.root / "06-sprints/approved").glob("*.md")))
        self.assertFalse(list((self.root / "06-sprints/proposed").glob("*.md")))

    def test_proposed_rejection_keeps_sources_active(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        response = client.post(f"/sprints/{record_id}/action", data={"action": "reject"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(list((self.root / "06-sprints/rejected").glob("*.md")))
        self.assertFalse(list((self.root / "04-inbox/thought-box/digested").glob("*.md")))
        self.assertTrue((self.root / "06-sprints/proposed").exists())

    def test_completion_update_by_code_works(self) -> None:
        self._create_sprint_record("approved")
        client = self._client()
        response = client.post(
            "/sprints/code/IMS-SPRINT-20260620-001/action",
            data={"confirm": "yes", "action": "stage", "completion_notes": "Validated in browser."},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        record = viewer_app._sprint_record_by_code("IMS-SPRINT-20260620-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["status_key"], "staged")
        text = (self.root / "06-sprints/staged/sp-20260620120000-approved-ims-sprint.md").read_text(encoding="utf-8")
        self.assertIn("Validated in browser.", text)

    def test_approval_creates_sprint_record_and_handoff(self) -> None:
        preview = viewer_app._digest_preview(viewer_app._thought_box_items(digested_only=False))
        response = self._client().post("/api/assistant/approve-digest", json={"digest_preview": preview})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["created_sprints"])
        self.assertTrue(body["created_handoffs"])
        self.assertTrue(list((self.root / "06-sprints/approved").glob("*.md")))
        self.assertTrue(list((self.root / "05-sprint-handoffs").glob("*.md")))
        self.assertTrue(list((self.root / "04-inbox/thought-box/digested").glob("*.md")))
        record = viewer_app._sprint_records()[0]
        self.assertTrue(record["source_thought_paths"])
        self.assertTrue(record["source_idea_summaries"])
        self.assertIn("Completion Requirement", record["handoff_markdown"])
        self.assertIn("Source Ideas", record["handoff_markdown"])
        self.assertIn("mark the sprint staged", record["handoff_markdown"].lower())

    def test_regenerate_handoff_repairs_source_sections(self) -> None:
        record_path = self._create_sprint_record("approved")
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertIsNotNone(record)
        record_path.write_text(
            "\n".join(
                [
                    "# Sprint Queue Record: IMS Sprint",
                    "",
                    "- sprint_id: sp-20260620120000-approved",
                    "- sprint_code: IMS-SPRINT-20260620-001",
                    "- app_product: IMS",
                    "- status: approved",
                    "- scope: Small",
                    "- idea_count: 2",
                    "- created_at: 2026-06-20T12:00:00Z",
                    "- updated_at: 2026-06-20T12:30:00Z",
                    "- handoff_path: 05-sprint-handoffs/2026-06-20-120000-ims-sprint.md",
                    "- purpose: Simplify queue workflows.",
                    "- recommended_first_step: Review the source ideas.",
                    "",
                    "## Source Ideas",
                    "- Inbox and Sprint Queue filters should auto-apply when changed.",
                    "- Simplify the Inbox navigation and reduce visible category clutter.",
                    "",
                    "## Source Thought Paths",
                    "- 04-inbox/thought-box/ims-ui.md",
                    "- 04-inbox/thought-box/worklog-queue.md",
                    "",
                    "## Source Idea Summaries",
                    "- Inbox and Sprint Queue filters should auto-apply when changed.",
                    "- Simplify the Inbox navigation and reduce visible category clutter.",
                    "",
                    "## Digested Source Ideas",
                    "- 04-inbox/thought-box/digested/ims-ui.md",
                    "- 04-inbox/thought-box/digested/worklog-queue.md",
                    "",
                    "## Proposed Work",
                    "- Improve the IMS queue surface.",
                    "- Tighten Worklog queue filtering.",
                    "",
                    "## Handoff Markdown",
                    "05-sprint-handoffs/2026-06-20-120000-ims-sprint.md",
                    "",
                    "## Codex/ChatGPT Starting Prompt",
                    "Start a focused implementation conversation.",
                    "",
                    "## Completion Requirement",
                    "When this sprint is complete, update Worklog using Sprint Code IMS-SPRINT-20260620-001.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (self.root / "05-sprint-handoffs/2026-06-20-120000-ims-sprint.md").write_text(
            "# Sprint Handoff: IMS Sprint\n\n## Source Ideas\n- Old placeholder\n\n## Proposed Work\n- Old placeholder\n",
            encoding="utf-8",
        )
        response = self._client().post("/sprints/sp-20260620120000-approved/action", data={"action": "regenerate_handoff"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        handoff_text = (self.root / "05-sprint-handoffs/2026-06-20-120000-ims-sprint.md").read_text(encoding="utf-8")
        self.assertIn("Inbox and Sprint Queue filters should auto-apply when changed.", handoff_text)
        self.assertIn("Simplify the Inbox navigation and reduce visible category clutter.", handoff_text)
        self.assertIn("Completion Requirement", handoff_text)
        self.assertIn("Codex/ChatGPT Starting Prompt", handoff_text)
        self.assertIn("mark the sprint staged", handoff_text.lower())

    def test_dashboard_shows_staged_counts(self) -> None:
        self._create_sprint_record("staged", title="IMS Staged", app_product="IMS")
        counts = viewer_app._sprint_counts_by_app()
        self.assertEqual(counts["IMS"]["staged"], 1)

    def test_regenerate_all_handoffs_action_runs(self) -> None:
        self._create_sprint_record("approved", title="IMS Sprint A")
        self._create_sprint_record("approved", title="IMS Sprint B")
        response = self._client().post("/sprints/regenerate-handoffs", data={"confirm": "yes"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertGreaterEqual(len(body["regenerated"]), 2)

    def test_dashboard_sprint_counts_work(self) -> None:
        self._create_sprint_record("approved")
        self._create_sprint_record("active", title="IMS Active", app_product="IMS")
        counts = viewer_app._sprint_counts_by_app()
        self.assertEqual(counts["IMS"]["approved"], 1)
        self.assertEqual(counts["IMS"]["active"], 1)

    def test_source_traceability_preserved(self) -> None:
        self._create_sprint_record("approved")
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertIsNotNone(record)
        self.assertIn("04-inbox/thought-box/ims-ui.md", record["source_thoughts"])
        self.assertIn("Sprint Handoff: IMS Sprint", record["handoff_markdown"])

    def test_lookup_by_code_works(self) -> None:
        self._create_sprint_record("approved")
        record = viewer_app._sprint_record_by_code("IMS-SPRINT-20260620-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["sprint_code"], "IMS-SPRINT-20260620-001")


if __name__ == "__main__":
    unittest.main()
