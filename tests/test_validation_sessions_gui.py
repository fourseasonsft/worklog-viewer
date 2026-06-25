from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as viewer_app
import validation_session_lib as validation_sessions


class ValidationSessionGuiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ["05-sprint-handoffs/validation-sessions", "07-validation-sessions"]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        self.old_root = viewer_app.WORKLOG_ROOT
        self.old_thought = viewer_app.THOUGHT_BOX_DIR
        self.old_handoffs = viewer_app.SPRINT_HANDOFFS_DIR
        viewer_app.WORKLOG_ROOT = self.root
        viewer_app.THOUGHT_BOX_DIR = self.root / "04-inbox/thought-box"
        viewer_app.SPRINT_HANDOFFS_DIR = self.root / "05-sprint-handoffs"
        self._seed_session()

    def tearDown(self) -> None:
        viewer_app.WORKLOG_ROOT = self.old_root
        viewer_app.THOUGHT_BOX_DIR = self.old_thought
        viewer_app.SPRINT_HANDOFFS_DIR = self.old_handoffs
        self.tmp.cleanup()

    def _seed_session(self) -> None:
        data = validation_sessions.seed_session_payload()
        data["slug"] = "ims-warehouse-foundation-release-1-0-validation"
        data["handoff_path"] = "05-sprint-handoffs/validation-sessions/ims-warehouse-foundation-release-1-0-validation.md"
        validation_sessions.write_session(self.root / "07-validation-sessions/ims-warehouse-foundation-release-1-0-validation.md", data)

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

    def test_validation_sessions_list_renders(self) -> None:
        html = self._client().get("/validation-sessions").get_data(as_text=True)
        self.assertIn("Validation Sessions", html)
        self.assertIn("IMS Warehouse Foundation Release 1.0 Validation", html)
        self.assertIn("Enterprise Shipment Management", html)
        base_html = self._client().get("/assistant").get_data(as_text=True)
        self.assertIn(">Validation Sessions<", base_html)

    def test_validation_session_detail_renders(self) -> None:
        html = self._client().get("/validation-sessions/ims-warehouse-foundation-release-1-0-validation").get_data(as_text=True)
        self.assertIn("Fill the survey quickly with pass / fail / pending / blocked / N/A, then add notes and findings where needed.", html)
        self.assertIn("Break Bulk Intake Wizard", html)
        self.assertIn("Pass", html)
        self.assertIn("Fail", html)
        self.assertIn("Pending", html)
        self.assertIn("Blocked", html)
        self.assertIn("N/A", html)
        self.assertIn('name="item_notes_break-bulk-intake-wizard"', html)
        self.assertIn("finding_details_break-bulk-intake-wizard", html)
        self.assertIn("Generate Handoff", html)
        self.assertIn("📋 Copy Handoff", html)
        self.assertIn("🤖 Copy AI Prompt", html)
        self.assertIn("Include notes", html)
        self.assertIn("Include passed items", html)
        self.assertIn("Include pending items", html)
        self.assertIn("Include blocked items", html)
        self.assertIn("Include N/A items", html)
        self.assertIn("Include finding summaries", html)
        self.assertEqual(html.count('<form method="post" id="validation-session-form">'), 1)
        self.assertIn('type="submit" name="action" value="save_all"', html)
        self.assertIn('type="submit" name="action" value="generate_handoff"', html)
        self.assertIn('type="submit" name="action" value="save_item"', html)
        self.assertNotIn('<form method="post"><form', html)

    def test_validation_session_save_item_updates_fields(self) -> None:
        response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation",
            data={
                "action": "save_item",
                "item_id": "break-bulk-intake-wizard",
                "item_status_break-bulk-intake-wizard": "fail",
                "item_notes_break-bulk-intake-wizard": "HTTP 400 confirmed in DEV.",
                "item_finding_severity_break-bulk-intake-wizard": "P1 Release Blocker",
                "item_finding_summary_break-bulk-intake-wizard": "Save still fails.",
                "session_status": "in_progress",
                "final_recommendation": "Review the blocker first.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Validation item saved.", text)
        session_path = self.root / "07-validation-sessions/ims-warehouse-foundation-release-1-0-validation.md"
        saved = session_path.read_text(encoding="utf-8")
        self.assertIn('status: "fail"', saved)
        self.assertIn('notes: "HTTP 400 confirmed in DEV."', saved)
        self.assertIn('finding_severity: "P1 Release Blocker"', saved)
        self.assertIn('finding_summary: "Save still fails."', saved)
        self.assertIn('final_recommendation: "Review the blocker first."', saved)

    def test_validation_session_save_pass_item_updates_notes(self) -> None:
        response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation",
            data={
                "action": "save_item",
                "item_id": "internal-pallet-ids",
                "item_status_internal-pallet-ids": "pass",
                "item_notes_internal-pallet-ids": "Verified in DEV.",
                "item_finding_severity_internal-pallet-ids": "",
                "item_finding_summary_internal-pallet-ids": "",
                "session_status": "in_progress",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        saved = (self.root / "07-validation-sessions/ims-warehouse-foundation-release-1-0-validation.md").read_text(encoding="utf-8")
        self.assertIn('status: "pass"', saved)
        self.assertIn('notes: "Verified in DEV."', saved)

    def test_validation_session_save_all_and_generate_handoff(self) -> None:
        response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation",
            data={
                "action": "save_all",
                "session_status": "blocked",
                "final_recommendation": "Resolve the intake wizard save issue.",
                "item_status_break-bulk-intake-wizard": "fail",
                "item_notes_break-bulk-intake-wizard": "Still reproduces.",
                "item_finding_severity_break-bulk-intake-wizard": "P1 Release Blocker",
                "item_finding_summary_break-bulk-intake-wizard": "Save still fails.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Validation session saved.", response.get_data(as_text=True))
        handoff_response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation",
            data={"action": "generate_handoff", "session_status": "blocked", "final_recommendation": "Resolve the intake wizard save issue."},
            follow_redirects=True,
        )
        self.assertEqual(handoff_response.status_code, 200)
        self.assertIn("ChatGPT handoff generated.", handoff_response.get_data(as_text=True))
        handoff_path = self.root / "05-sprint-handoffs/validation-sessions/ims-warehouse-foundation-release-1-0-validation.md"
        self.assertTrue(handoff_path.exists())
        self.assertIn("Validation Session Handoff", handoff_path.read_text(encoding="utf-8"))

    def test_validation_session_generate_handoff_page_round_trip(self) -> None:
        response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation",
            data={
                "action": "generate_handoff",
                "session_status": "blocked",
                "final_recommendation": "Resolve the intake wizard save issue.",
                "include_notes": "1",
                "include_passed": "1",
                "include_pending": "1",
                "include_blocked": "1",
                "include_na": "1",
                "include_finding_summaries": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("ChatGPT handoff generated.", text)
        self.assertIn("Handoff Path", text)
        self.assertIn("validation-sessions/ims-warehouse-foundation-release-1-0-validation.md", text)
        self.assertIn("Validation Session Handoff", text)
        self.assertIn("Analyze the following Operational Validation Session.", text)

    def test_validation_session_generate_handoff_json_and_prompt(self) -> None:
        response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation?format=json",
            data={
                "action": "generate_handoff",
                "include_notes": "1",
                "include_passed": "1",
                "include_pending": "1",
                "include_blocked": "1",
                "include_na": "1",
                "include_finding_summaries": "1",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("handoff_path", payload)
        self.assertIn("Validation Session Handoff", payload["handoff_markdown"])
        self.assertIn("Analyze the following Operational Validation Session.", payload["ai_prompt"])
        self.assertIn("=== VALIDATION HANDOFF ===", payload["ai_prompt"])
        self.assertIn("Internal Pallet IDs", payload["handoff_markdown"])
        self.assertIn("Status: PASS", payload["handoff_markdown"])

    def test_validation_session_mark_completed(self) -> None:
        response = self._client().post(
            "/validation-sessions/ims-warehouse-foundation-release-1-0-validation",
            data={
                "action": "set_status",
                "target_status": "completed",
                "session_status": "completed",
                "final_recommendation": "Ready to ship.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Validation session marked completed.", text)
        saved = (self.root / "07-validation-sessions/ims-warehouse-foundation-release-1-0-validation.md").read_text(encoding="utf-8")
        self.assertIn('status: "completed"', saved)
        self.assertIn("completed_at:", saved)


if __name__ == "__main__":
    unittest.main()
