from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as viewer_app


class WorklogDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._make_structure()
        self.old_root = viewer_app.WORKLOG_ROOT
        viewer_app.WORKLOG_ROOT = self.root

    def tearDown(self) -> None:
        viewer_app.WORKLOG_ROOT = self.old_root
        self.tmp.cleanup()

    def _make_structure(self) -> None:
        for rel in [
            "00-dashboard",
            "01-daily-logs/2026/06",
            "03-active-work",
            "04-inbox/new",
            "04-inbox/bugs",
            "04-inbox/features",
            "04-inbox/support",
            "04-inbox/closed",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        for name, body in {
            "portfolio-status.md": "# Portfolio Status\n\n- Worklog is the daily command center.\n",
            "engineering-priorities.md": "# Engineering Priorities\n\n| Priority | Application | Objective | Status | Why It Matters | Next Action |\n| --- | --- | --- | --- | --- | --- |\n| P1 | IMS | Fix box quantity support | Active | Needed for receiving | Define data model |\n",
            "current-focus.md": "# Current Focus\n\n- Keep the day simple.\n",
            "next-actions.md": "# Next Actions\n\n- Finish intake.\n- Validate the dashboard.\n",
            "where-we-left-off.md": "# Where We Left Off\n\n- Ready to redesign the dashboard.\n",
            "blockers.md": "# Blockers\n\n- None.\n",
        }.items():
            (self.root / "00-dashboard" / name).write_text(body, encoding="utf-8")
        (self.root / "01-daily-logs/2026/06/2026-06-20.md").write_text("# Daily Log - 2026-06-20\n", encoding="utf-8")
        for name in ["core", "unity", "ims", "dispatch", "parking", "cy-storage", "worklog"]:
            (self.root / "03-active-work" / f"{name}.md").write_text(
                "# Worklog Active Work\n\n## Current Sprint / Focus\n\n- Keep moving.\n\n## Blockers\n\n- None.\n\n## Last Updated\n\n- 2026-06-20\n",
                encoding="utf-8",
            )
        (self.root / "04-inbox/new/example.md").write_text(
            "# Example\n\n- Type: Note\n- App: Worklog\n- Summary: Example note\n- Status: new\n- Created: 2026-06-20\n- Owner: David\n",
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

    def test_homepage_renders_focus_layout(self) -> None:
        response = self._client().get("/")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("What needs attention now?", html)
        self.assertIn("Quick shortcut to Idea Inventory", html)
        self.assertIn("Active, proposed, and shipped updates", html)
        self.assertNotIn("Promote", html)
        self.assertNotIn("Mark reviewed", html)
        self.assertNotIn("Details last", html)

    def test_intake_route_renders_capture_page(self) -> None:
        response = self._client().get("/intake")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Structured Intake", html)
        self.assertIn("Create structured work item", html)

    def test_intake_form_creates_markdown_item(self) -> None:
        response = self._client().post(
            "/intake",
            data={
                "title": "New bug from test",
                "type": "bug",
                "app_project": "worklog",
                "priority": "high",
                "plain_english_summary": "Dashboard copy should be calmer.",
                "technical_notes": "Update landing layout.",
                "source": "Unit test",
                "requested_by": "David",
                "next_action": "Review layout update.",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        created = list((self.root / "04-inbox/bugs").glob("*new-bug-from-test.md"))
        self.assertEqual(len(created), 1)
        content = created[0].read_text(encoding="utf-8")
        self.assertIn("Plain English Summary", content)
        self.assertIn("Technical Notes", content)

    def test_dashboard_counts_still_work(self) -> None:
        counts = viewer_app._dashboard_counts()
        self.assertEqual(counts["open_new"], 1)
        self.assertEqual(counts["open_bugs"], 0)


if __name__ == "__main__":
    unittest.main()
