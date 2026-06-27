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
            "# IMS Sprint\n\n- Sprint Code: IMS-SPRINT-20260626-002\n- Status: active\n- App: IMS\n",
            encoding="utf-8",
        )
        (self.root / "04-inbox" / "requests").mkdir(parents=True, exist_ok=True)
        (self.root / "04-inbox" / "requests" / "2026-06-27-shortcode-test.md").write_text(
            "# Shortcode Test\n\n- request_id: 04-inbox/requests/2026-06-27-shortcode-test.md\n- request_title: Shortcode Test\n- requester_email: david@example.com\n- shortcode: SHORTCODE-ENGINE-001\n",
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


if __name__ == "__main__":
    unittest.main()
