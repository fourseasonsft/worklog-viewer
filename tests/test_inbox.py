from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as viewer_app


class WorklogInboxTests(unittest.TestCase):
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
            "03-active-work",
            "04-inbox/new",
            "04-inbox/bugs",
            "04-inbox/features",
            "04-inbox/support",
            "04-inbox/closed",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "00-dashboard/portfolio-status.md").write_text("# Portfolio Status\n", encoding="utf-8")
        (self.root / "00-dashboard/engineering-priorities.md").write_text("# Engineering Priorities\n", encoding="utf-8")
        for name in ["core", "unity", "ims", "dispatch", "parking", "cy-storage", "hiring", "worklog"]:
            (self.root / "03-active-work" / f"{name}.md").write_text("# Active Work\n", encoding="utf-8")
        items = {
            "04-inbox/bugs/2026-06-20-parking-door.md": "# Parking bug\n\n- Title: Parking door issue\n- App: Parking\n- Priority: high\n- Status: open\n- Source: Unit test\n- Summary: Parking bug summary\n",
            "04-inbox/features/2026-06-20-ims-box.md": "# IMS feature\n\n- Title: IMS box request\n- App/Project: IMS\n- Priority: medium\n- Status: open\n- Source: Unit test\n- Summary: IMS feature summary\n",
            "04-inbox/support/2026-06-20-worklog-help.md": "# Worklog support\n\n- Title: Worklog help needed\n- App: Worklog\n- Priority: low\n- Status: open\n- Source: Unit test\n- Summary: Support summary\n",
            "04-inbox/new/2026-06-20-hiring-note.md": "# Hiring note\n\n- Title: Hiring note\n- App: Hiring\n- Priority: medium\n- Status: open\n- Source: Unit test\n- Summary: Hiring note summary\n",
            "04-inbox/closed/2026-06-19-parking-closed.md": "# Parking closed\n\n- Title: Closed parking item\n- App: Parking\n- Priority: low\n- Status: closed\n- Source: Unit test\n- Summary: Closed parking summary\n",
        }
        for path, body in items.items():
            (self.root / path).write_text(body, encoding="utf-8")

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

    def test_inbox_renders_table(self) -> None:
        response = self._client().get("/inbox")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Operational inbox", html)
        self.assertIn("Type", html)
        self.assertIn("App / Product", html)
        self.assertIn("Parking bug", html)
        self.assertNotIn("Closed parking item", html)

    def test_inbox_all_excludes_closed(self) -> None:
        html = self._client().get("/inbox?type=all").get_data(as_text=True)
        self.assertIn("Parking bug", html)
        self.assertIn("IMS box request", html)
        self.assertNotIn("Closed parking item", html)

    def test_inbox_closed_shows_only_closed(self) -> None:
        html = self._client().get("/inbox?type=closed").get_data(as_text=True)
        self.assertIn("Closed parking item", html)
        self.assertNotIn("Parking bug", html)
        self.assertNotIn("IMS box request", html)

    def test_inbox_type_filter_works(self) -> None:
        html = self._client().get("/inbox?type=bugs").get_data(as_text=True)
        self.assertIn("Parking bug", html)
        self.assertNotIn("IMS box request", html)

    def test_inbox_app_filter_works(self) -> None:
        html = self._client().get("/inbox?app=parking").get_data(as_text=True)
        self.assertIn("Parking bug", html)
        self.assertNotIn("IMS box request", html)
        self.assertNotIn("Hiring note", html)

    def test_inbox_combined_type_and_app_filter_works(self) -> None:
        html = self._client().get("/inbox?type=bugs&app=parking").get_data(as_text=True)
        self.assertIn("Parking bug", html)
        self.assertNotIn("IMS box request", html)

    def test_dashboard_inbox_links_include_app_param(self) -> None:
        html = self._client().get("/").get_data(as_text=True)
        self.assertIn("/inbox?app=parking", html)
        self.assertIn("/inbox?app=ims", html)
        self.assertIn("/inbox?app=worklog", html)

    def test_legacy_inbox_routes_redirect(self) -> None:
        self.assertEqual(self._client().get("/inbox/new").status_code, 302)
        self.assertEqual(self._client().get("/inbox/bugs").status_code, 302)
        self.assertEqual(self._client().get("/inbox/features").status_code, 302)
        self.assertEqual(self._client().get("/inbox/support").status_code, 302)
        self.assertEqual(self._client().get("/inbox/closed").status_code, 302)

    def test_empty_state_renders_cleanly(self) -> None:
        for path in (self.root / "04-inbox/new").glob("*.md"):
            path.unlink()
        for path in (self.root / "04-inbox/bugs").glob("*.md"):
            path.unlink()
        for path in (self.root / "04-inbox/features").glob("*.md"):
            path.unlink()
        for path in (self.root / "04-inbox/support").glob("*.md"):
            path.unlink()
        html = self._client().get("/inbox").get_data(as_text=True)
        self.assertIn("No inbox items match the selected filters.", html)


if __name__ == "__main__":
    unittest.main()
