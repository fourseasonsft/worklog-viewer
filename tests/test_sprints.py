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
            "06-sprints/shipped",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
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
        path = self.root / f"06-sprints/{status}/sp-20260620120000-{status}-{title.lower().replace(' ', '-')}.md"
        path.write_text(
            "\n".join(
                [
                    f"# Sprint Queue Record: {title}",
                    "",
                    f"- sprint_id: sp-20260620120000-{status}",
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
                    "Start a focused implementation conversation.",
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

    def test_sprint_queue_page_renders(self) -> None:
        self._create_sprint_record("approved")
        html = self._client().get("/sprints").get_data(as_text=True)
        self.assertIn("Sprint Queue", html)
        self.assertIn("IMS Sprint", html)
        self.assertIn("Start Sprint", html)
        self.assertIn("onchange=\"this.form.requestSubmit()\"", html)

    def test_filters_work(self) -> None:
        self._create_sprint_record("approved")
        self._create_sprint_record("shipped", title="Worklog Sprint", app_product="Worklog")
        client = self._client()
        approved_html = client.get("/sprints?status=approved").get_data(as_text=True)
        self.assertIn("IMS Sprint", approved_html)
        self.assertNotIn("Worklog Sprint", approved_html)
        shipped_html = client.get("/sprints?status=shipped").get_data(as_text=True)
        self.assertIn("Worklog Sprint", shipped_html)
        self.assertNotIn("IMS Sprint", shipped_html)
        ims_html = client.get("/sprints?app=ims").get_data(as_text=True)
        self.assertIn("IMS Sprint", ims_html)
        self.assertNotIn("Worklog Sprint", ims_html)
        combo_html = client.get("/sprints?status=approved&app=ims").get_data(as_text=True)
        self.assertIn("IMS Sprint", combo_html)

    def test_detail_page_renders(self) -> None:
        self._create_sprint_record("approved")
        html = self._client().get("/sprints/sp-20260620120000-approved").get_data(as_text=True)
        self.assertIn("Sprint Queue Record", html)
        self.assertIn("Generated Handoff", html)
        self.assertIn("Copy Prompt", html)
        self.assertIn("Copy Handoff", html)

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
        response = client.post("/sprints/sp-20260620120000-approved/action", data={"action": "ship"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        shipped_path = self.root / "06-sprints/shipped/sp-20260620120000-approved-ims-sprint.md"
        self.assertTrue(shipped_path.exists())

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

    def test_dashboard_sprint_counts_work(self) -> None:
        self._create_sprint_record("approved")
        self._create_sprint_record("active", title="IMS Active", app_product="IMS")
        counts = viewer_app._sprint_counts_by_app()
        self.assertEqual(counts["IMS"]["approved"], 1)
        self.assertEqual(counts["IMS"]["active"], 1)
        html = self._client().get("/").get_data(as_text=True)
        self.assertIn("/sprints?app=ims&amp;status=active", html)
        self.assertIn("/sprints?app=ims&amp;status=approved", html)

    def test_source_traceability_preserved(self) -> None:
        self._create_sprint_record("approved")
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertIsNotNone(record)
        self.assertIn("04-inbox/thought-box/ims-ui.md", record["source_thoughts"])
        self.assertIn("Sprint Handoff: IMS Sprint", record["handoff_markdown"])


if __name__ == "__main__":
    unittest.main()
