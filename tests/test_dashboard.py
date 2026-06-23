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
        active_work_bodies = {
            "core": "# Core Active Work\n\n## Current State\n\n- Core is stable.\n\n## Last Sprint\n\n- Name: Registry alignment\n- Completed: 2026-06-19\n- Outcome: Worklog launch stayed aligned.\n\n## Next Suggested Sprint\n\n- Name: Launch stability watch\n- Why: Keep the assertion path stable.\n- Suggested First Step: Verify launcher payloads.\n\n## Current Sprint / Focus\n\n- Keep Core stable.\n\n## Blockers\n\n- None.\n\n## Last Updated\n\n- 2026-06-20\n",
            "unity": "# Unity Active Work\n\n## Current State\n\n- Unity is stable.\n\n## Last Sprint\n\n- Name: Launcher alignment\n- Completed: 2026-06-19\n- Outcome: Worklog stayed visible.\n\n## Next Suggested Sprint\n\n- Name: Launcher visibility verification\n- Why: Keep Super Admin access working.\n- Suggested First Step: Confirm Worklog launch.\n\n## Current Sprint / Focus\n\n- Keep Unity stable.\n\n## Blockers\n\n- None.\n\n## Last Updated\n\n- 2026-06-20\n",
            "ims": "# IMS Active Work\n\n## Current State\n\n- IMS reconciliation is active.\n\n## Current Sprint\n\n- Name: IMS reconciliation and shipment UI alignment\n- Status: Active\n- Percent Complete: 65%\n- Started: 2026-06-18\n- Target: 2026-06-24\n- Notes: Keep the workflow aligned.\n\n## Blockers\n\n- Remove/Rescind review still open.\n\n## Last Updated\n\n- 2026-06-20\n",
            "dispatch": "# Dispatch Active Work\n\n## Current State\n\n- Dispatch v0 is implemented.\n\n## Last Sprint\n\n- Name: v0 stabilization\n- Completed: 2026-06-19\n- Outcome: v0 surface remained stable.\n\n## Next Suggested Sprint\n\n- Name: Intake queue and document ingestion\n- Why: Remaining product step.\n- Suggested First Step: Define minimum fields.\n\n## Current Sprint / Focus\n\n- Keep Dispatch stable.\n\n## Blockers\n\n- None.\n\n## Last Updated\n\n- 2026-06-20\n",
            "parking": "# Parking Active Work\n\n## Current State\n\n- Parking work is paused.\n\n## Last Sprint\n\n- Name: Agreement rendering quality review\n- Completed: 2026-06-20\n- Outcome: Worklog stabilization stayed the priority.\n\n## Next Suggested Sprint\n\n- Name: Agreement package rendering cleanup\n- Why: Resume after stabilization.\n- Suggested First Step: Recheck DOCX rendering.\n\n## Current Sprint / Focus\n\n- Keep Parking paused.\n\n## Blockers\n\n- Worklog stabilization.\n\n## Last Updated\n\n- 2026-06-20\n",
            "cy-storage": "# CY Storage Active Work\n\n## Current State\n\n- CY Storage expansion is active.\n\n## Current Sprint\n\n- Name: Phase 4 billing-unit and charge-master expansion\n- Status: Active\n- Percent Complete: 55%\n- Started: 2026-06-10\n- Target: 2026-06-28\n- Notes: Keep the phase 4 expansion moving.\n\n## Blockers\n\n- None.\n\n## Last Updated\n\n- 2026-06-20\n",
            "hiring": "# Hiring Active Work\n\n## Current State\n\n- Hiring docking remains active.\n\n## Current Sprint\n\n- Name: Standalone Hiring docking and production MVP validation\n- Status: Active\n- Percent Complete: 80%\n- Started: 2026-06-18\n- Target: 2026-06-30\n- Notes: Keep the standalone service aligned.\n\n## Blockers\n\n- Service restart still pending.\n\n## Last Updated\n\n- 2026-06-20\n",
            "worklog": "# Worklog Active Work\n\n## Current State\n\n- Worklog is the active project memory system.\n\n## Last Sprint\n\n- Name: Command center visual redesign\n- Completed: 2026-06-20\n- Outcome: Dashboard now leads with app cards.\n\n## Next Suggested Sprint\n\n- Name: App-by-app portfolio card refinement\n- Why: Keep the attention surface focused.\n- Suggested First Step: Verify browser rendering.\n\n## Current Sprint / Focus\n\n- Keep Worklog stable.\n\n## Blockers\n\n- None.\n\n## Last Updated\n\n- 2026-06-20\n",
        }
        for name, body in active_work_bodies.items():
            (self.root / "03-active-work" / f"{name}.md").write_text(body, encoding="utf-8")
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

    def test_dashboard_renders_table_and_rows(self) -> None:
        html = self._client().get("/").get_data(as_text=True)
        self.assertIn("dashboard-table", html)
        self.assertIn("dashboard-table-th-rotated", html)
        self.assertIn("App/Product", html)
        self.assertIn("Core", html)
        self.assertIn("Unity", html)
        self.assertIn("Worklog", html)
        self.assertIn("IMS", html)
        self.assertIn("CY Storage", html)
        self.assertIn("Dispatch", html)
        self.assertIn("Parking", html)
        self.assertIn("Hiring", html)
        self.assertIn("Other", html)
        self.assertIn("/sprints?app=worklog&amp;status=proposed", html)
        self.assertIn("/sprints?app=worklog&amp;status=approved", html)
        self.assertIn("/sprints?app=worklog&amp;status=active", html)
        self.assertIn("/sprints?app=worklog&amp;status=done", html)
        self.assertIn("/sprints?app=worklog&amp;status=staged", html)
        self.assertIn("/sprints?app=worklog&amp;status=shipped", html)
        self.assertIn("/inbox?app=worklog", html)

    def test_dashboard_does_not_render_recent_pages(self) -> None:
        html = self._client().get("/").get_data(as_text=True)
        self.assertNotIn("Recent Pages", html)

    def test_dashboard_route_returns_200(self) -> None:
        response = self._client().get("/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_includes_next_action_and_notes(self) -> None:
        html = self._client().get("/").get_data(as_text=True)
        self.assertIn("Blockers / Notes", html)
        self.assertIn("Next Action", html)


if __name__ == "__main__":
    unittest.main()
