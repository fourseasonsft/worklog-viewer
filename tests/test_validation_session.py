from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class ValidationSessionCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ["05-sprint-handoffs", "07-validation-sessions"]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        self.script = Path("/opt/fsftdev/worklog-viewer/scripts/validation_session.py")
        self.python = Path("/opt/fsftdev/worklog-viewer/.venv/bin/python")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = "/opt/fsftdev/worklog-viewer"
        return subprocess.run(
            [str(self.python), str(self.script), "--worklog-root", str(self.root), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_create_update_generate_and_complete_session(self) -> None:
        created = self._run("create", "--seed", "ims-warehouse-foundation-release-1.0", "--json-output")
        self.assertEqual(created.returncode, 0, created.stderr)
        payload = json.loads(created.stdout)
        session_path = Path(payload["path"])
        self.assertTrue(session_path.exists())
        self.assertIn("ims-warehouse-foundation-release-1-0-validation.md", session_path.name)
        session_text = session_path.read_text(encoding="utf-8")
        self.assertIn('title: "IMS Warehouse Foundation Release 1.0 Validation"', session_text)
        self.assertIn('status: "in_progress"', session_text)
        self.assertIn('Break Bulk Intake Wizard save fails with HTTP 400.', session_text)

        updated = self._run(
            "update-item",
            "--session",
            "ims-warehouse-foundation-release-1-0-validation",
            "--id",
            "break-bulk-intake-wizard",
            "--status",
            "fail",
            "--notes",
            "HTTP 400 confirmed during save.",
            "--finding-severity",
            "P1 Release Blocker",
            "--finding-summary",
            "Save still fails.",
            "--json-output",
        )
        self.assertEqual(updated.returncode, 0, updated.stderr)
        session_text = session_path.read_text(encoding="utf-8")
        self.assertIn('notes: "HTTP 400 confirmed during save."', session_text)
        self.assertIn('finding_summary: "Save still fails."', session_text)

        handoff = self._run("generate-handoff", "--session", "ims-warehouse-foundation-release-1-0-validation", "--json-output")
        self.assertEqual(handoff.returncode, 0, handoff.stderr)
        handoff_payload = json.loads(handoff.stdout)
        handoff_path = Path(handoff_payload["handoff_path"])
        self.assertTrue(handoff_path.exists())
        handoff_text = handoff_path.read_text(encoding="utf-8")
        self.assertIn("Validation Session Handoff: IMS Warehouse Foundation Release 1.0 Validation", handoff_text)
        self.assertIn("Fail Count: 1", handoff_text)
        self.assertIn("P1 Release Blocker: 1", handoff_text)
        self.assertIn("Recommended Next Action", handoff_text)

        completed = self._run("complete", "--session", "ims-warehouse-foundation-release-1-0-validation", "--json-output")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        session_text = session_path.read_text(encoding="utf-8")
        self.assertIn('status: "completed"', session_text)
        self.assertIn("completed_at:", session_text)


if __name__ == "__main__":
    unittest.main()
