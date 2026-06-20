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
        viewer_app.WORKLOG_ROOT = self.root
        viewer_app.THOUGHT_BOX_DIR = self.root / "04-inbox/thought-box"
        viewer_app.app.config["OPENAI_API_KEY"] = ""

    def tearDown(self) -> None:
        viewer_app.WORKLOG_ROOT = self.old_root
        viewer_app.THOUGHT_BOX_DIR = self.old_thought
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

    def test_assistant_renders(self) -> None:
        response = self._client().get("/assistant")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Worklog Assistant", response.get_data(as_text=True))
        self.assertIn("Active thought table", response.get_data(as_text=True))

    def test_message_stores_raw_thought(self) -> None:
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

    def test_missing_openai_key_is_safe(self) -> None:
        response = self._client().post("/api/assistant/message", json={"message": "hi"})
        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("OpenAI is not configured", body["assistant_reply"])

    def test_digest_preview_reads_undigested_thought_files(self) -> None:
        thought = self.root / "04-inbox/thought-box/2026-06-20-100000-ims-break-bulk.md"
        thought.write_text(
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
            encoding="utf-8",
        )
        before = sorted(p.name for p in (self.root / "04-inbox/thought-box").glob("*.md"))
        response = self._client().get("/assistant?digest_preview=1")
        after = sorted(p.name for p in (self.root / "04-inbox/thought-box").glob("*.md"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(before, after)
        self.assertIn("Digest preview", response.get_data(as_text=True))
        self.assertIn("Proposed items", response.get_data(as_text=True))

    def test_digest_preview_does_not_move_files(self) -> None:
        thought = self.root / "04-inbox/thought-box/2026-06-20-110000-general.md"
        thought.write_text(
            "# General\n\n- created_at: 2026-06-20T11:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: General thought.\n",
            encoding="utf-8",
        )
        _ = self._client().get("/assistant?digest_preview=1")
        self.assertTrue(thought.exists())
        self.assertEqual(thought.parent.name, "thought-box")

    def test_digest_command_does_not_create_raw_thought(self) -> None:
        response = self._client().post("/api/assistant/message", json={"message": "digest my thought box"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertFalse(body["created_raw_thought"])
        self.assertIn("digest_preview", body)
        self.assertEqual(list((self.root / "04-inbox/thought-box").glob("*.md")), [])

    def test_no_thoughts_empty_state_works(self) -> None:
        response = self._client().get("/assistant")
        html = response.get_data(as_text=True)
        self.assertIn("No active raw thoughts yet.", html)

    def test_approve_digest_creates_items_and_moves_thoughts(self) -> None:
        thought1 = self.root / "04-inbox/thought-box/2026-06-20-100000-ims.md"
        thought1.write_text(
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
            encoding="utf-8",
        )
        thought2 = self.root / "04-inbox/thought-box/2026-06-20-100001-ims-2.md"
        thought2.write_text(
            "# IMS 2\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
            encoding="utf-8",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/approve-digest", json={"digest_preview": preview})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["created_items"])
        self.assertTrue(body["moved_thoughts"])
        self.assertTrue(list((self.root / "04-inbox/features").glob("*.md")))
        self.assertTrue(list((self.root / "04-inbox/thought-box/digested").glob("*.md")))
        self.assertTrue(list((self.root / "05-release-notes/assistant-update-shipments").glob("*.md")))
        html = self._client().get("/assistant").get_data(as_text=True)
        self.assertIn("No active raw thoughts yet.", html)

    def test_update_bundle_tracked_separately(self) -> None:
        thought = self.root / "04-inbox/thought-box/2026-06-20-130000-ims.md"
        thought.write_text(
            "# IMS\n\n- created_at: 2026-06-20T13:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs a barcode update.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs a barcode update.\n",
            encoding="utf-8",
        )
        preview = self._client().post("/api/assistant/digest-preview", json={}).get_json()["digest_preview"]
        response = self._client().post("/api/assistant/approve-digest", json={"digest_preview": preview})
        self.assertEqual(response.status_code, 200)
        update_files = list((self.root / "05-release-notes/assistant-update-shipments").glob("*.md"))
        self.assertEqual(len(update_files), 1)
        self.assertIn("shipped/live", update_files[0].read_text(encoding="utf-8"))

    def test_archive_thought_moves_raw_file(self) -> None:
        thought = self.root / "04-inbox/thought-box/2026-06-20-120000-note.md"
        thought.write_text(
            "# Note\n\n- created_at: 2026-06-20T12:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Archive this.\n",
            encoding="utf-8",
        )
        response = self._client().post("/api/assistant/archive-thought", json={"thought_path": "04-inbox/thought-box/2026-06-20-120000-note.md"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(thought.exists())
        self.assertTrue((self.root / "04-inbox/thought-box/archived/2026-06-20-120000-note.md").exists())


if __name__ == "__main__":
    unittest.main()
