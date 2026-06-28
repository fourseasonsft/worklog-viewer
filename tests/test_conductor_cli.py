from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts import conductor


class ConductorCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "00-dashboard").mkdir(parents=True, exist_ok=True)
        (self.root / "03-active-work").mkdir(parents=True, exist_ok=True)
        (self.root / "06-sprints" / "active").mkdir(parents=True, exist_ok=True)
        (self.root / "00-dashboard" / "current-focus.md").write_text("# Current Focus\n\n- Stabilize Conductor.\n", encoding="utf-8")
        (self.root / "03-active-work" / "ims.md").write_text("# IMS Active Work\n", encoding="utf-8")
        (self.root / "03-active-work" / "worklog.md").write_text("# Worklog Active Work\n", encoding="utf-8")
        (self.root / "06-sprints" / "active" / "IMS-SPRINT-20260626-002.md").write_text(
            "# IMS Sprint\n\n- Sprint Code: IMS-SPRINT-20260626-002\n- Status: active\n- App: IMS\n- Recommended First Step: Document the candidate row lifecycle, allowable edits, and Convert Intake boundary before implementation.\n",
            encoding="utf-8",
        )
        (self.root / "04-inbox" / "requests").mkdir(parents=True, exist_ok=True)
        (self.root / "04-inbox" / "requests" / "2026-06-27-shortcode-test.md").write_text(
            "# Shortcode Test\n\n- request_id: 04-inbox/requests/2026-06-27-shortcode-test.md\n- request_title: Shortcode Test\n- requester_email: david@example.com\n- shortcode: SHORTCODE-ENGINE-001\n",
            encoding="utf-8",
        )
        (self.root / "07-work-orders").mkdir(parents=True, exist_ok=True)
        (self.root / "07-work-orders" / "WO-20260627-012-work-order-follow-up-routing.md").write_text(
            "# WO-20260627-012-work-order-follow-up-routing\n\n"
            "Status: Requested\n"
            "Created: 2026-06-28\n"
            "Requested By: David\n"
            "Primary App: Worklog\n"
            "Secondary System: Conductor\n"
            "Related Codex Shortcode: `/codex:fsft-work-order`\n\n"
            "## Objective\n\n"
            "Implement Work Order follow-up routing.\n\n"
            "## Prerequisites\n\n"
            "- sprint activation follow-up: completed\n"
            "- documentation boundary: complete\n\n"
            "## Pending Follow-Ups\n\n"
            "- Implement the smallest safe routing patch for `#/work-order fu <id>` so a single pending follow-up can be executed automatically.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_brief_current_json_and_log(self) -> None:
        code = conductor.main(["--worklog-root", str(self.root), "--json", "brief", "current"])
        self.assertEqual(code, 0)
        log_path = self.root / "08-conductor" / "command-log.jsonl"
        self.assertTrue(log_path.exists())
        entry = json.loads(log_path.read_text(encoding="utf-8").strip())
        self.assertEqual(entry["command"], "brief current")
        self.assertEqual(entry["approval_status"], "not_required")

    def test_brief_sprint_json(self) -> None:
        code = conductor.main(["--worklog-root", str(self.root), "--json", "brief", "sprint", "IMS-SPRINT-20260626-002"])
        self.assertEqual(code, 0)

    def test_report_today_json(self) -> None:
        code = conductor.main(["--worklog-root", str(self.root), "--json", "report", "today"])
        self.assertEqual(code, 0)

    def test_missing_sprint_returns_error(self) -> None:
        code = conductor.main(["--worklog-root", str(self.root), "--json", "brief", "sprint", "MISSING"])
        self.assertEqual(code, 1)

    def test_shortcode_resolve_writes_result_artifact(self) -> None:
        code = conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "shortcode",
            "resolve",
            "SHORTCODE-ENGINE-001",
        ])
        self.assertEqual(code, 0)
        notifications = sorted((self.root / "04-inbox" / "notifications").glob("*shortcode-result*.md"))
        self.assertEqual(len(notifications), 1)
        content = notifications[0].read_text(encoding="utf-8")
        self.assertIn("shortcode_result", content)
        self.assertIn("RESULT_SHORTCODE", content)
        self.assertIn("SHORTCODE-ENGINE-001", content)

    def test_work_order_fu_routes_single_pending_follow_up(self) -> None:
        code = conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "work-order",
            "fu",
            "WO-20260627-012-work-order-follow-up-routing",
        ])
        self.assertEqual(code, 0)
        log_path = self.root / "08-conductor" / "command-log.jsonl"
        self.assertTrue(log_path.exists())
        entry = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(entry["command"], "work-order fu WO-20260627-012-work-order-follow-up-routing")
        self.assertEqual(entry["approval_status"], "not_required")

    def test_work_order_fu_advances_past_completed_prerequisite(self) -> None:
        code = conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "work-order",
            "fu",
            "WO-20260627-012-work-order-follow-up-routing",
        ])
        self.assertEqual(code, 0)
        entry = json.loads((self.root / "08-conductor" / "command-log.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(entry["command"], "work-order fu WO-20260627-012-work-order-follow-up-routing")
        self.assertEqual(entry["output_summary"], "Work order WO-20260627-012-work-order-follow-up-routing has no pending follow-ups")

    def test_work_order_issue_creates_issue_and_packet(self) -> None:
        code = conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "work-order",
            "issue",
            "WO-20260627-014-work-order-issuance-transaction",
            "--title",
            "Work Order Issuance Transaction",
            "--objective",
            "Implement Work Order issuance transactionally.",
        ])
        self.assertEqual(code, 0)
        issue_path = self.root / "04-inbox" / "requests" / "WO-20260627-014-work-order-issuance-transaction.md"
        work_order_path = self.root / "07-work-orders" / "WO-20260627-014-work-order-issuance-transaction.md"
        self.assertTrue(issue_path.exists())
        self.assertTrue(work_order_path.exists())
        content = work_order_path.read_text(encoding="utf-8")
        self.assertIn("Transactional issuance should create both", content)
        self.assertIn("Work Order ID: WO-20260627-014-work-order-issuance-transaction", issue_path.read_text(encoding="utf-8"))

    def test_work_order_issue_rolls_back_on_partial_failure(self) -> None:
        original = conductor._work_order_packet_artifact

        def fail_once(root, work_order_id, title, objective):
            raise RuntimeError("simulated failure")

        conductor._work_order_packet_artifact = fail_once
        try:
            with self.assertRaises(RuntimeError):
                conductor.issue_work_order(
                    self.root,
                    "WO-20260627-014-work-order-issuance-transaction",
                    "Work Order Issuance Transaction",
                    "Implement Work Order issuance transactionally.",
                )
        finally:
            conductor._work_order_packet_artifact = original
        issue_path = self.root / "04-inbox" / "requests" / "WO-20260627-014-work-order-issuance-transaction.md"
        work_order_path = self.root / "07-work-orders" / "WO-20260627-014-work-order-issuance-transaction.md"
        self.assertFalse(issue_path.exists())
        self.assertFalse(work_order_path.exists())

    def test_sprint_repair_followups_seeds_missing_active_follow_up(self) -> None:
        code = conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "sprint",
            "repair-followups",
        ])
        self.assertEqual(code, 0)
        seeded = self.root / "07-work-orders" / "IMS-SPRINT-20260626-002.md"
        self.assertTrue(seeded.exists())
        seeded_text = seeded.read_text(encoding="utf-8")
        self.assertIn("Document the candidate row lifecycle", seeded_text)

    def test_work_order_fu_after_repair_routes_seeded_follow_up(self) -> None:
        conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "sprint",
            "repair-followups",
        ])
        code = conductor.main([
            "--worklog-root",
            str(self.root),
            "--json",
            "work-order",
            "fu",
            "IMS-SPRINT-20260626-002",
        ])
        self.assertEqual(code, 0)
        log_path = self.root / "08-conductor" / "command-log.jsonl"
        entry = json.loads(log_path.read_text(encoding="utf-8").strip().splitlines()[-1])
        self.assertEqual(entry["command"], "work-order fu IMS-SPRINT-20260626-002")
        self.assertEqual(entry["approval_status"], "not_required")


if __name__ == "__main__":
    unittest.main()
