from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import json
import subprocess
import os

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
            "06-sprints/done",
            "06-sprints/reconciled",
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

    def _write_thought(self, name: str, body: str) -> Path:
        path = self.root / "04-inbox/thought-box" / name
        path.write_text(body, encoding="utf-8")
        return path

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

    def _create_legacy_approved_record(self, sprint_code: str, filename: str, title: str, app_product: str = "Other") -> Path:
        path = self.root / f"06-sprints/approved/{filename}"
        path.write_text(
            "\n".join(
                [
                    f"# Sprint Queue Record: {title}",
                    "",
                    f"- sprint_code: {sprint_code}",
                    f"- app_product: {app_product}",
                    "- status: approved",
                    "- scope: Small",
                    "- created_at: 2026-06-20T21:57:10Z",
                    "",
                    "## Source Ideas",
                    "- Legacy idea.",
                    "",
                    "## Proposed Work",
                    "- Legacy idea.",
                    "",
                    "## Handoff Markdown",
                    "05-sprint-handoffs/legacy.md",
                    "",
                    "## Completion Requirement",
                    f"When this sprint is complete, update Worklog using Sprint Code {sprint_code}.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _create_sprint_record_with_code(self, status: str, sprint_code: str, filename: str, title: str, app_product: str = "Other") -> Path:
        path = self.root / f"06-sprints/{status}/{filename}"
        path.write_text(
            "\n".join(
                [
                    f"# Sprint Queue Record: {title}",
                    "",
                    f"- sprint_code: {sprint_code}",
                    f"- app_product: {app_product}",
                    f"- status: {status}",
                    "- scope: Small",
                    "- created_at: 2026-06-20T21:57:10Z",
                    "- updated_at: 2026-06-20T21:57:10Z",
                    "",
                    "## Source Ideas",
                    "- Legacy idea.",
                    "",
                    "## Proposed Work",
                    "- Legacy idea.",
                    "",
                    "## Handoff Markdown",
                    "05-sprint-handoffs/legacy.md",
                    "",
                ]
            ),
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
                    f"- intended_sprint_code: {sprint_code}",
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
                    "## Sprint Code",
                    sprint_code,
                    "",
                    "## Source Ideas",
                    "- Improve the IMS queue surface.",
                    "- Tighten Worklog queue filtering.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return path

    def _create_worklog_proposed_record(self, title: str = "Worklog Proposed") -> Path:
        return self._create_proposed_sprint_record(title=title, app_product="Worklog")

    def _run_create_sprint_cli(self, *args: str, worklog_root: Path | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path("/opt/fsftdev/worklog-viewer"))
        cmd = [
            "/opt/fsftdev/worklog-viewer/.venv/bin/python",
            "scripts/create_sprint.py",
            *args,
        ]
        if worklog_root is not None:
            cmd.extend(["--worklog-root", str(worklog_root)])
        return subprocess.run(
            cmd,
            cwd="/opt/fsftdev/worklog-viewer",
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_sprint_queue_page_renders(self) -> None:
        self._create_sprint_record("active")
        html = self._client().get("/sprints").get_data(as_text=True)
        self.assertIn("Sprint Queue", html)
        self.assertIn("Sprint Code", html)
        self.assertIn("IMS Sprint", html)
        self.assertIn("onchange=\"this.form.requestSubmit()\"", html)
        self.assertIn("Mark Complete", html)
        self.assertIn("Mark Done", html)

    def test_proposed_filter_renders_proposed_rows(self) -> None:
        self._create_proposed_sprint_record()
        html = self._client().get("/sprints?status=proposed").get_data(as_text=True)
        self.assertIn("IMS Proposed", html)
        self.assertIn("Approve", html)
        self.assertIn("Reject", html)
        self.assertNotIn("Mark Done", html)

    def test_mark_done_action_moves_record_to_done_queue(self) -> None:
        self._create_sprint_record("active", app_product="Worklog", title="Worklog Sprint")
        record = viewer_app._sprint_records()[0]
        client = self._client()
        response = client.post(
            f"/sprints/code/{record['sprint_code']}/action",
            data={"action": "mark_done", "confirm": "yes"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        done_records = viewer_app._sprint_records()
        self.assertEqual(len([record for record in done_records if record["status_key"] == "done"]), 1)
        record = done_records[0]
        self.assertEqual(record["sprint_code"], "WL-SPRINT-20260620-001")
        self.assertTrue(record["done_at"])
        self.assertIn("Reconciliation Pending", (self.root / record["path"]).read_text(encoding="utf-8"))
        done_html = client.get("/sprints?status=done").get_data(as_text=True)
        self.assertIn("Worklog Sprint", done_html)
        self.assertIn("Done", done_html)

    def test_mark_done_legacy_record_overwrites_existing_done_target(self) -> None:
        self._create_legacy_approved_record(
            "OTHER-SPRINT-20260620-001",
            "sp-20260620215733-other-reporting.md",
            "Other reporting",
        )
        existing_done = self.root / "06-sprints/done/sp-20260620215733-other-reporting.md"
        existing_done.write_text(
            "# Sprint Queue Record: Other reporting\n\n- sprint_code: OTHER-SPRINT-20260620-001\n- status: done\n",
            encoding="utf-8",
        )
        response = self._client().post(
            "/sprints/code/OTHER-SPRINT-20260620-001/action",
            data={"action": "mark_done", "confirm": "yes"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Duplicate sprint code conflict", response.get_data(as_text=True))

    def test_duplicate_sprint_code_lookup_warns_and_blocks_mutation(self) -> None:
        self._create_sprint_record_with_code("done", "OTHER-SPRINT-20260620-001", "sp-20260620215733-other-reporting.md", "Other reporting")
        self._create_sprint_record_with_code("shipped", "OTHER-SPRINT-20260620-001", "sp-20260620221220-sprint.md", "Other reporting shipped")
        record = viewer_app._sprint_record_by_code("OTHER-SPRINT-20260620-001")
        self.assertIsNotNone(record)
        self.assertTrue(record["duplicate_conflict"])
        self.assertIn("Duplicate sprint code resolved", record["duplicate_warning"])
        self.assertEqual(record["status_key"], "shipped")
        response = self._client().post(
            "/sprints/code/OTHER-SPRINT-20260620-001/action",
            data={"action": "mark_done", "confirm": "yes"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Duplicate sprint code conflict", response.get_data(as_text=True))

    def test_duplicate_terminal_records_prefer_shipped_when_canonical(self) -> None:
        self._create_sprint_record_with_code("done", "OTHER-SPRINT-20260620-001", "sp-20260620215733-other-reporting.md", "Other reporting")
        self._create_sprint_record_with_code("shipped", "OTHER-SPRINT-20260620-001", "sp-20260620221220-sprint.md", "Other reporting shipped")
        record = viewer_app._sprint_record_by_code("OTHER-SPRINT-20260620-001")
        self.assertEqual(record["status_key"], "shipped")

    def test_mark_done_legacy_minimal_fields(self) -> None:
        self._create_legacy_approved_record(
            "OTHER-SPRINT-20260620-002",
            "sp-20260620215733-other-follow-up.md",
            "Other follow-up",
        )
        record_id = viewer_app._sprint_records()[0]["id"]
        response = self._client().post(
            "/sprints/code/OTHER-SPRINT-20260620-002/action",
            data={"action": "mark_done", "confirm": "yes"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        done_records = viewer_app._sprint_records()
        done_record = next(record for record in done_records if record["sprint_code"] == "OTHER-SPRINT-20260620-002")
        self.assertEqual(done_record["status_key"], "done")
        self.assertTrue(done_record["done_at"])
        self.assertIn("Reconciliation Pending", (self.root / done_record["path"]).read_text(encoding="utf-8"))

    def test_resolved_duplicates_do_not_interfere_with_code_lookup(self) -> None:
        shipped = self._create_sprint_record_with_code("shipped", "OTHER-SPRINT-20260620-001", "sp-20260620221220-sprint.md", "Other reporting shipped")
        done = self._create_sprint_record_with_code("done", "OTHER-SPRINT-20260620-001", "sp-20260620215733-other-reporting.md", "Other reporting")
        duplicate_dir = self.root / "06-sprints/duplicates"
        duplicate_dir.mkdir(parents=True, exist_ok=True)
        done.rename(duplicate_dir / done.name)
        record = viewer_app._sprint_record_by_code("OTHER-SPRINT-20260620-001")
        self.assertEqual(record["status_key"], "shipped")
        self.assertFalse(record.get("duplicate_conflict"))
        self.assertEqual(record["path"], "06-sprints/shipped/sp-20260620221220-sprint.md")

    def test_create_sprint_cli_creates_proposed_sprint(self) -> None:
        result = self._run_create_sprint_cli(
            "--app",
            "Worklog",
            "--title",
            "Dashboard Portfolio Header Rotation",
            "--source-idea",
            "Portfolio table looks good from proposed to inbox; put the table headers at 45 degree angle.",
            "--scope",
            "Small",
            worklog_root=self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        created = list((self.root / "06-sprints/proposed").glob("*.md"))
        self.assertEqual(len(created), 1)
        content = created[0].read_text(encoding="utf-8")
        self.assertIn("Dashboard Portfolio Header Rotation", content)
        self.assertIn("Portfolio table looks good from proposed to inbox; put the table headers at 45 degree angle.", content)
        self.assertIn("## Codex/ChatGPT Starting Prompt", content)
        self.assertIn("## Handoff Preview", content)

    def test_create_sprint_cli_does_not_duplicate_repeated_source_idea(self) -> None:
        first = self._run_create_sprint_cli(
            "--app",
            "Worklog",
            "--title",
            "Dashboard Portfolio Header Rotation",
            "--source-idea",
            "Portfolio table looks good from proposed to inbox; put the table headers at 45 degree angle.",
            "--scope",
            "Small",
            worklog_root=self.root,
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self._run_create_sprint_cli(
            "--app",
            "Worklog",
            "--title",
            "Dashboard Portfolio Header Rotation",
            "--source-idea",
            "Portfolio table looks good from proposed to inbox; put the table headers at 45 degree angle.",
            "--scope",
            "Small",
            worklog_root=self.root,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("Duplicate sprint already exists", second.stdout)
        self.assertEqual(len(list((self.root / "06-sprints/proposed").glob("*.md"))), 1)

    def test_create_sprint_cli_preserves_multiple_source_ideas(self) -> None:
        result = self._run_create_sprint_cli(
            "--app",
            "Worklog",
            "--title",
            "Dashboard Portfolio Header Rotation",
            "--source-idea",
            "First source idea.",
            "--source-idea",
            "Second source idea.",
            "--scope",
            "Small",
            worklog_root=self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        content = next((self.root / "06-sprints/proposed").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("First source idea.", content)
        self.assertIn("Second source idea.", content)

    def test_create_sprint_cli_json_output(self) -> None:
        result = self._run_create_sprint_cli(
            "--app",
            "Worklog",
            "--title",
            "Dashboard Portfolio Header Rotation",
            "--source-idea",
            "Portfolio table looks good from proposed to inbox; put the table headers at 45 degree angle.",
            "--scope",
            "Small",
            "--json-output",
            worklog_root=self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.strip())
        self.assertTrue(payload["created"])
        self.assertFalse(payload["duplicate"])
        self.assertTrue(payload["sprint_code"])
        self.assertTrue(payload["proposal_id"])
        self.assertTrue(payload["record_path"])
        self.assertIn("## Sprint Code", payload["handoff_preview"])

    def test_create_sprint_cli_custom_worklog_root(self) -> None:
        result = self._run_create_sprint_cli(
            "--app",
            "Worklog",
            "--title",
            "Custom Root Sprint",
            "--source-idea",
            "Custom root works.",
            "--scope",
            "Small",
            worklog_root=self.root,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "06-sprints/proposed").exists())

    def test_mark_done_does_not_appear_on_proposed_or_shipped(self) -> None:
        self._create_proposed_sprint_record()
        self._create_sprint_record("shipped", title="IMS Shipped")
        html = self._client().get("/sprints").get_data(as_text=True)
        self.assertNotIn("Mark Done", html)

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
        visible = html.split("Debug metadata")[0]
        self.assertIn("Handoff Preview", visible)
        self.assertIn("Sprint Code", visible)
        self.assertIn("WL-SPRINT-20260620-001", visible)
        self.assertIn("Improve the IMS queue surface.", visible)
        self.assertIn("Tighten Worklog queue filtering.", visible)
        self.assertIn("Improve the IMS queue surface.", visible)

    def test_proposed_handoff_uses_intended_code_and_same_sources(self) -> None:
        self._create_proposed_sprint_record(title="Worklog Idea Inventory UI Cleanup", app_product="Worklog")
        record = viewer_app._sprint_records()[0]
        html = self._client().get(f"/sprints/{record['id']}").get_data(as_text=True)
        self.assertIn("WL-SPRINT-20260620-001", html)
        self.assertNotIn("PR-20260620120000-001", html)
        self.assertIn("Improve the IMS queue surface.", html)
        self.assertIn("Tighten Worklog queue filtering.", html)

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

    def test_queue_excludes_rescinded_and_deleted_by_default(self) -> None:
        self._create_sprint_record("approved", title="Queue Archive Candidate", app_product="IMS")
        client = self._client()
        record = viewer_app._sprint_records()[0]
        client.post(f"/sprints/{record['id']}/action", data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"}, follow_redirects=True)
        rescinded_html = client.get("/sprints?status=rescinded").get_data(as_text=True)
        self.assertIn("Queue Archive Candidate", rescinded_html)
        archived = viewer_app._sprint_records()[0]
        client.post(f"/sprints/{archived['id']}/action", data={"action": "delete", "confirm": "delete this sprint record and return its ideas to inventory?"}, follow_redirects=True)
        html = client.get("/sprints").get_data(as_text=True)
        self.assertNotIn("Queue Archive Candidate", html)
        deleted_html = client.get("/sprints?status=deleted").get_data(as_text=True)
        self.assertIn("Queue Archive Candidate", deleted_html)

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
        self.assertIn("Mark Done", html)

    def test_active_detail_shows_mark_complete_and_mark_done(self) -> None:
        self._create_sprint_record("active")
        html = self._client().get("/sprints/sp-20260620120000-active").get_data(as_text=True)
        self.assertIn("Mark Complete", html)
        self.assertIn("Mark Done", html)
        self.assertIn("Mark Complete generates draft release notes for review.", html)
        self.assertIn("Mark Done moves the sprint to the Done queue for later Codex reconciliation.", html)

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

    def test_mark_complete_generates_release_notes(self) -> None:
        self._create_sprint_record("active", app_product="Worklog", title="Worklog Sprint")
        client = self._client()
        response = client.post(
            "/sprints/sp-20260620120000-active/action",
            data={"action": "complete"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Draft release notes generated. Please review before shipping.", response.get_data(as_text=True))
        completed_record = viewer_app._sprint_record_by_id("sp-20260620120000-active")
        self.assertIsNotNone(completed_record)
        self.assertEqual(completed_record["status_key"], "completed")
        self.assertTrue(completed_record.get("internal_release_notes"))
        self.assertTrue(completed_record.get("plain_english_release_notes"))
        detail_html = client.get("/sprints/sp-20260620120000-active").get_data(as_text=True)
        self.assertIn("Mark Done", detail_html)
        self.assertIn("Release Notes", detail_html)

    def test_mark_complete_uses_complete_action(self) -> None:
        self._create_sprint_record("approved")
        response = self._client().post(
            "/sprints/sp-20260620120000-approved/action",
            data={"action": "complete"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Draft release notes generated. Please review before shipping.", response.get_data(as_text=True))
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertEqual(record["status_key"], "completed")

    def test_shared_completed_status_update_backfills_release_notes(self) -> None:
        path = self._create_sprint_record("approved", title="Worklog Sprint", app_product="Worklog")
        completed_path = viewer_app._update_sprint_record(path, "completed")
        record = viewer_app._parse_sprint_record(completed_path)
        self.assertEqual(record["status_key"], "completed")
        self.assertTrue(str(record.get("internal_release_notes") or "").strip())
        self.assertTrue(str(record.get("plain_english_release_notes") or "").strip())

    def test_mark_done_alias_still_routes_to_done_flow(self) -> None:
        self._create_sprint_record("active", app_product="Worklog", title="Worklog Sprint")
        response = self._client().post(
            "/sprints/code/WL-SPRINT-20260620-001/action",
            data={"action": "mark_done", "confirm": "yes"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        record = viewer_app._sprint_record_by_code("WL-SPRINT-20260620-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["status_key"], "done")

    def test_proposed_rescind_restores_ideas(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record = viewer_app._sprint_records()[0]
        response = client.post(f"/sprints/{record['id']}/action", data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Restored", response.get_data(as_text=True))
        self.assertTrue(list((self.root / "06-sprints/rescinded").glob("*.md")))
        thoughts = client.get("/api/assistant/thoughts").get_json()["thoughts"]
        self.assertTrue(any(thought["raw_text_full"] == "Improve the IMS queue surface." for thought in thoughts))
        self.assertTrue(any(thought["raw_text_full"] == "Tighten Worklog queue filtering." for thought in thoughts))
        self.assertTrue(all(thought["digest_status"] == "not_digested" for thought in thoughts if thought["raw_text_full"] in {"Improve the IMS queue surface.", "Tighten Worklog queue filtering."}))

    def test_proposed_delete_restores_ideas(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record = viewer_app._sprint_records()[0]
        response = client.post(f"/sprints/{record['id']}/action", data={"action": "delete", "confirm": "delete this sprint record and return its ideas to inventory?"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Restored", response.get_data(as_text=True))
        self.assertTrue(list((self.root / "06-sprints/deleted").glob("*.md")))
        thoughts = client.get("/api/assistant/thoughts").get_json()["thoughts"]
        self.assertTrue(any(thought["raw_text_full"] == "Improve the IMS queue surface." for thought in thoughts))
        self.assertTrue(any(thought["raw_text_full"] == "Tighten Worklog queue filtering." for thought in thoughts))

    def test_proposed_approval_moves_to_approved_and_digests_sources(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        before = viewer_app._sprint_records()[0]["intended_sprint_code"]
        response = client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        approved = viewer_app._sprint_records()[0]
        self.assertEqual(approved["sprint_code"], before)
        self.assertTrue(list((self.root / "06-sprints/approved").glob("*.md")))
        self.assertFalse(list((self.root / "06-sprints/proposed").glob("*.md")))

    def test_same_proposed_create_request_returns_existing_sprint(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-idempotent.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer inbox queue.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer inbox queue.\n",
        )
        client = self._client()
        preview = viewer_app._digest_preview([item for item in viewer_app._thought_box_items(digested_only=False) if item["path"].endswith("worklog-idempotent.md")])
        first = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(first.status_code, 200)
        second = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(second.status_code, 200)
        body = second.get_json()
        self.assertIn("A sprint already exists for these ideas.", body["assistant_reply"])
        proposed_records = [record for record in viewer_app._proposed_sprint_records() if str(record.get("status") or "").lower() == "proposed"]
        self.assertEqual(len(proposed_records), 1)

    def test_combine_all_double_submit_creates_one_proposal(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-combine.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer inbox queue.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer inbox queue.\n",
        )
        client = self._client()
        preview = viewer_app._digest_preview([item for item in viewer_app._thought_box_items(digested_only=False) if item["path"].endswith("worklog-combine.md")])
        first = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "combine_all"})
        self.assertEqual(first.status_code, 200)
        second = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "combine_all"})
        self.assertEqual(second.status_code, 200)
        self.assertIn("A sprint already exists for these ideas.", second.get_json()["assistant_reply"])
        self.assertEqual(len(viewer_app._proposed_sprint_records()), 1)

    def test_suggested_group_double_submit_creates_one_proposal(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-suggested.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer inbox queue.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer inbox queue.\n",
        )
        client = self._client()
        preview = viewer_app._digest_preview([item for item in viewer_app._thought_box_items(digested_only=False) if item["path"].endswith("worklog-suggested.md")])
        first = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(first.status_code, 200)
        second = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(second.status_code, 200)
        self.assertIn("A sprint already exists for these ideas.", second.get_json()["assistant_reply"])
        self.assertEqual(len(viewer_app._proposed_sprint_records()), 1)

    def test_approve_same_proposal_twice_does_not_duplicate(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-approve.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer inbox queue.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer inbox queue.\n",
        )
        client = self._client()
        preview = viewer_app._digest_preview([item for item in viewer_app._thought_box_items(digested_only=False) if item["path"].endswith("worklog-approve.md")])
        created = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(created.status_code, 200)
        proposal = viewer_app._proposed_sprint_records()[0]
        first = client.post(f"/sprints/{proposal['proposal_id']}/action", data={"action": "approve"}, follow_redirects=True)
        self.assertEqual(first.status_code, 200)
        second = client.post(f"/sprints/{proposal['proposal_id']}/action", data={"action": "approve"}, follow_redirects=True)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len([record for record in viewer_app._sprint_records() if record["status_key"] == "approved"]), 1)

    def test_duplicate_detection_spans_proposed_and_approved_records(self) -> None:
        self._write_thought(
            "2026-06-20-100000-worklog-dup.md",
            "# Worklog\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs a calmer inbox queue.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs a calmer inbox queue.\n",
        )
        client = self._client()
        preview = viewer_app._digest_preview([item for item in viewer_app._thought_box_items(digested_only=False) if item["path"].endswith("worklog-dup.md")])
        created = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(created.status_code, 200)
        proposal = viewer_app._proposed_sprint_records()[0]
        client.post(f"/sprints/{proposal['proposal_id']}/action", data={"action": "approve"}, follow_redirects=True)
        response = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("A sprint already exists for these ideas.", response.get_json()["assistant_reply"])
        self.assertEqual(len([record for record in viewer_app._sprint_records() if record["status_key"] == "approved"]), 1)

    def test_regenerate_handoff_does_not_create_duplicate_sprint(self) -> None:
        self._create_sprint_record("approved")
        client = self._client()
        before = len(viewer_app._sprint_records())
        response = client.post("/sprints/sp-20260620120000-approved/action", data={"action": "regenerate_handoff"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(viewer_app._sprint_records()), before)

    def test_proposed_rejection_keeps_sources_active(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        response = client.post(f"/sprints/{record_id}/action", data={"action": "reject"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(list((self.root / "06-sprints/rejected").glob("*.md")))
        self.assertFalse(list((self.root / "04-inbox/thought-box/digested").glob("*.md")))
        self.assertTrue((self.root / "06-sprints/proposed").exists())

    def test_approved_rescind_restores_ideas_and_moves_handoff(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        approved = viewer_app._sprint_records()[0]
        response = client.post(
            f"/sprints/{approved['id']}/action",
            data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Restored", response.get_data(as_text=True))
        self.assertTrue(list((self.root / "06-sprints/rescinded").glob("*.md")))
        self.assertTrue(list((self.root / "05-sprint-handoffs/rescinded").glob("*.md")))
        thoughts = client.get("/api/assistant/thoughts").get_json()["thoughts"]
        self.assertTrue(any(thought["raw_text_full"] == "Improve the IMS queue surface." for thought in thoughts))
        self.assertTrue(any(thought["raw_text_full"] == "Tighten Worklog queue filtering." for thought in thoughts))
        restored = next(thought for thought in thoughts if thought["raw_text_full"] == "Improve the IMS queue surface.")
        self.assertNotEqual(restored["created_display"], "Unknown")

    def test_approved_delete_restores_ideas_and_moves_handoff(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        approved = viewer_app._sprint_records()[0]
        response = client.post(
            f"/sprints/{approved['id']}/action",
            data={"action": "delete", "confirm": "delete this sprint record and return its ideas to inventory?"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Restored", response.get_data(as_text=True))
        self.assertTrue(list((self.root / "06-sprints/deleted").glob("*.md")))
        self.assertTrue(list((self.root / "05-sprint-handoffs/deleted").glob("*.md")))
        thoughts = client.get("/api/assistant/thoughts").get_json()["thoughts"]
        self.assertTrue(any(thought["raw_text_full"] == "Improve the IMS queue surface." for thought in thoughts))
        self.assertTrue(any(thought["raw_text_full"] == "Tighten Worklog queue filtering." for thought in thoughts))
        restored = next(thought for thought in thoughts if thought["raw_text_full"] == "Improve the IMS queue surface.")
        self.assertNotEqual(restored["created_display"], "Unknown")

    def test_existing_active_ideas_are_not_duplicated(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        active_file = self.root / "04-inbox/thought-box/ims-ui.md"
        active_file.write_text("already active", encoding="utf-8")
        approved = viewer_app._sprint_records()[0]
        client.post(
            f"/sprints/{approved['id']}/action",
            data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"},
            follow_redirects=True,
        )
        restored_files = sorted((self.root / "04-inbox/thought-box").glob("ims-ui*.md"))
        self.assertEqual(active_file.read_text(encoding="utf-8"), "already active")
        self.assertTrue(restored_files)

    def test_missing_source_ideas_warn_but_do_not_crash(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        approved = viewer_app._sprint_records()[0]
        digested = self.root / "04-inbox/thought-box/digested"
        for path in digested.glob("*.md"):
            path.unlink()
        approved_path = self.root / "06-sprints/approved" / Path(approved["path"]).name
        text = approved_path.read_text(encoding="utf-8")
        text = text.replace("## Source Thought Paths\n- 04-inbox/thought-box/ims-ui.md\n- 04-inbox/thought-box/worklog-queue.md\n", "## Source Thought Paths\n- 04-inbox/thought-box/missing-a.md\n- 04-inbox/thought-box/missing-b.md\n")
        approved_path.write_text(text, encoding="utf-8")
        response = client.post(
            f"/sprints/{approved['id']}/action",
            data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        rescinded_path = next((self.root / "06-sprints/rescinded").glob("*.md"))
        content = rescinded_path.read_text(encoding="utf-8")
        self.assertIn("missing_source_ideas_count", content)

    def test_missing_source_file_is_recreated_from_summary(self) -> None:
        self._create_proposed_sprint_record()
        client = self._client()
        record_id = viewer_app._sprint_records()[0]["id"]
        client.post(f"/sprints/{record_id}/action", data={"action": "approve"}, follow_redirects=True)
        approved = viewer_app._sprint_records()[0]
        for rel in [
            "04-inbox/thought-box/ims-ui.md",
            "04-inbox/thought-box/worklog-queue.md",
            "04-inbox/thought-box/digested/ims-ui.md",
            "04-inbox/thought-box/digested/worklog-queue.md",
        ]:
            path = self.root / rel
            if path.exists():
                path.unlink()
        approved_path = self.root / "06-sprints/approved" / Path(approved["path"]).name
        text = approved_path.read_text(encoding="utf-8")
        text = text.replace(
            "- source_thought_paths: 04-inbox/thought-box/ims-ui.md, 04-inbox/thought-box/worklog-queue.md\n",
            "- source_thought_paths: 04-inbox/thought-box/missing-a.md, 04-inbox/thought-box/missing-b.md\n",
        )
        approved_path.write_text(text, encoding="utf-8")
        response = client.post(
            f"/sprints/{approved['id']}/action",
            data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        restored = sorted((self.root / "04-inbox/thought-box").glob("*.md"))
        self.assertTrue(restored)
        restored_text = restored[0].read_text(encoding="utf-8")
        self.assertIn("restored_from_sprint_code", restored_text)
        self.assertIn("restore_reason", restored_text)
        self.assertIn("Improve the IMS queue surface.", restored_text)

    def test_proposed_rescind_restores_test_idea_to_active_inventory(self) -> None:
        source = self.root / "04-inbox/thought-box/proposed/2026-06-22-193423-test.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            "# test\n\n- created_at: 2026-06-22T19:34:23Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: test\n- ai_inferred_app: \n- ai_inferred_type: thought\n- ai_summary: test\n",
            encoding="utf-8",
        )
        proposed = self.root / "06-sprints/proposed/pr-20260622193434-001-other-follow-up.md"
        proposed.write_text(
            "\n".join(
                [
                    "# Proposed Sprint Group: Other follow-up",
                    "",
                    "- proposal_id: pr-20260622193434-001",
                    "- intended_sprint_code: OTHER-SPRINT-20260622-006",
                    "- sprint_group_name: Other follow-up",
                    "- app_product: Other",
                    "- scope: Small",
                    "- status: proposed",
                    "- created_at: 2026-06-22T19:34:34.533360+00:00",
                    "- updated_at: 2026-06-22T19:34:34.533360+00:00",
                    "- source_thought_ids: 9f86d081884c7d65",
                    "- source_thought_paths: 04-inbox/thought-box/proposed/2026-06-22-193423-test.md",
                    "- source_created_ats: 2026-06-22T19:34:23Z",
                    "",
                    "## Source Ideas",
                    "- test",
                    "",
                    "## Source Idea Summaries",
                    "- test",
                    "",
                    "## Proposed Work",
                    "- test",
                    "",
                    "## Handoff Preview",
                    "# Sprint Handoff Preview\n\n## Source Ideas\n- Test123.\n\n## Proposed Work\n- Test123.\n\n## Codex/ChatGPT Starting Prompt\nTest123.",
                    "",
                    "## Codex/ChatGPT Starting Prompt",
                    "Test123.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        client = self._client()
        record = viewer_app._sprint_record_by_id("pr-20260622193434-001")
        self.assertIsNotNone(record)
        response = client.post(
            f"/sprints/{record['id']}/action",
            data={"action": "rescind", "confirm": "rescind this sprint and return its ideas to inventory?"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        thoughts = client.get("/api/assistant/thoughts").get_json()["thoughts"]
        self.assertTrue(any(thought["raw_text_full"] == "test" for thought in thoughts))
        self.assertTrue(any(thought["digest_status"] == "not_digested" for thought in thoughts if thought["raw_text_full"] == "test"))
        restored = next(thought for thought in thoughts if thought["raw_text_full"] == "test")
        self.assertNotEqual(restored["created_display"], "Unknown")
        self.assertTrue(restored.get("created_at") or restored.get("created_display"))

    def test_proposed_creation_moves_source_ideas_out_of_active_inventory(self) -> None:
        (self.root / "04-inbox/thought-box/2026-06-20-100000-ims.md").write_text(
            "# IMS\n\n- created_at: 2026-06-20T10:00:00Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: IMS needs break bulk handling.\n- ai_inferred_app: IMS\n- ai_inferred_type: feature\n- ai_summary: IMS needs break bulk handling.\n",
            encoding="utf-8",
        )
        (self.root / "04-inbox/thought-box/2026-06-20-100001-worklog.md").write_text(
            "# Worklog\n\n- created_at: 2026-06-20T10:00:01Z\n- source: David\n- status: raw\n- digest_status: not_digested\n- raw_text: Worklog needs queue selection.\n- ai_inferred_app: Worklog\n- ai_inferred_type: feature\n- ai_summary: Worklog needs queue selection.\n",
            encoding="utf-8",
        )
        preview = viewer_app._digest_preview(viewer_app._thought_box_items(digested_only=False))
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "combine_all"})
        self.assertEqual(response.status_code, 200)
        thoughts = self._client().get("/api/assistant/thoughts").get_json()["thoughts"]
        self.assertFalse(any(thought["raw_text_full"] == "IMS needs break bulk handling." for thought in thoughts))
        self.assertFalse(any(thought["raw_text_full"] == "Worklog needs queue selection." for thought in thoughts))

    def test_proposed_sprint_detail_uses_canonical_source_lists(self) -> None:
        path = self.root / "06-sprints/proposed/pr-20260622000000-legacy-dup.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "# Proposed Sprint Group: Legacy Dup",
                    "",
                    "- proposal_id: pr-20260622000000-001",
                    "- intended_sprint_code: WL-SPRINT-20260622-999",
                    "- sprint_group_name: Legacy Dup",
                    "- app_product: Worklog",
                    "- scope: Small",
                    "- status: proposed",
                    "- created_at: 2026-06-22T20:00:00Z",
                    "- updated_at: 2026-06-22T20:00:00Z",
                    "- source_thought_paths: 04-inbox/thought-box/test123.md",
                    "",
                    "## Source Ideas",
                    "- Test123.",
                    "",
                    "## Source Idea Summaries",
                    "- Test123.",
                    "",
                    "## Proposed Work",
                    "- Test123.",
                    "",
                    "## Handoff Preview",
                    "# Sprint Handoff Preview",
                    "",
                    "## Codex/ChatGPT Starting Prompt",
                    "Test123.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        record = next(item for item in viewer_app._proposed_sprint_records() if item["proposal_id"] == "pr-20260622000000-001")
        self.assertIsNotNone(record)
        with viewer_app.app.test_request_context():
            html = viewer_app.render_template("sprint_detail.html", record=record)
        visible = html.split("Debug metadata")[0]
        source_section = visible.split("Source Ideas")[1].split("Proposed Work")[0]
        proposed_section = visible.split("Proposed Work")[1].split("Handoff Preview")[0]
        self.assertEqual(source_section.count("Test123."), 1)
        self.assertEqual(proposed_section.count("Test123."), 1)
        self.assertIn("Source Ideas", visible)
        self.assertIn("Proposed Work", visible)
        self.assertIn("Handoff Preview", visible)
        self.assertIn("Codex Prompt", visible)

    def test_sprint_detail_renders_release_note_edit_fields(self) -> None:
        self._create_sprint_record("approved", app_product="Worklog", title="Worklog Sprint")
        client = self._client()
        html = client.get("/sprints/sp-20260620120000-approved").get_data(as_text=True)
        self.assertIn("Internal Release Notes", html)
        self.assertIn("Plain English Release Notes", html)
        self.assertIn("Save Release Notes", html)

    def test_sprint_detail_can_save_release_notes_and_preserve_metadata(self) -> None:
        path = self._create_sprint_record("approved", app_product="Worklog", title="Worklog Sprint")
        client = self._client()
        response = client.post(
            "/sprints/sp-20260620120000-approved",
            data={
                "action": "update_release_notes",
                "internal_release_notes": "Internal rollout note.",
                "plain_english_release_notes": "Plain English note.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        updated = path.read_text(encoding="utf-8")
        self.assertIn("- internal_release_notes: Internal rollout note.", updated)
        self.assertIn("- plain_english_release_notes: Plain English note.", updated)
        self.assertIn("- sprint_code: WL-SPRINT-20260620-001", updated)
        self.assertIn("- status: approved", updated)
        self.assertIn("- idea_count: 2", updated)
        self.assertIn("Release notes updated.", response.get_data(as_text=True))
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertIsNotNone(record)
        self.assertEqual(record["status_key"], "approved")
        self.assertEqual(record["sprint_code"], "WL-SPRINT-20260620-001")
        self.assertEqual(record["internal_release_notes"], "Internal rollout note.")
        self.assertEqual(record["plain_english_release_notes"], "Plain English note.")

    def test_sidebar_shows_single_inbox_link_and_pacific_timestamps(self) -> None:
        self._create_sprint_record("approved")
        html = self._client().get("/sprints").get_data(as_text=True)
        self.assertIn(">Inbox<", html)
        self.assertNotIn("Inbox / New", html)
        self.assertNotIn("Inbox / Bugs", html)
        self.assertNotIn("Inbox / Features", html)
        self.assertNotIn("Inbox / Support", html)
        self.assertNotIn("Inbox / Closed", html)
        self.assertRegex(html, r"2026-06-20\s+\d{1,2}:\d{2}\s+(AM|PM)\s+P[DS]T")

    def test_sprint_queue_idea_count_uses_canonical_source_ideas(self) -> None:
        path = self.root / "06-sprints/approved/sp-20260622000000-queue-count.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "# Sprint Queue Record: Queue Count",
                    "",
                    "- sprint_id: sp-20260622000000-approved",
                    "- sprint_code: WL-SPRINT-20260622-100",
                    "- app_product: Worklog",
                    "- status: approved",
                    "- scope: Small",
                    "- idea_count: 2",
                    "- created_at: 2026-06-22T20:00:00Z",
                    "- updated_at: 2026-06-22T20:00:00Z",
                    "",
                    "## Source Ideas",
                    "- Test123.",
                    "- Test123.",
                    "",
                    "## Source Idea Summaries",
                    "- Test123.",
                    "- Test123.",
                    "",
                    "## Proposed Work",
                    "- Test123.",
                    "- Test123.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        record = viewer_app._parse_sprint_record(path)
        self.assertEqual(record["idea_count"], 1)
        self.assertEqual(record["canonical_source_ideas"], ["Test123."])

    def test_proposed_queue_idea_count_uses_canonical_source_ideas(self) -> None:
        path = self.root / "06-sprints/proposed/pr-20260622000000-queue-count.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "\n".join(
                [
                    "# Proposed Sprint Group: Queue Count",
                    "",
                    "- proposal_id: pr-20260622000000-queue",
                    "- intended_sprint_code: WL-SPRINT-20260622-101",
                    "- sprint_group_name: Queue Count",
                    "- app_product: Worklog",
                    "- scope: Small",
                    "- status: proposed",
                    "- created_at: 2026-06-22T20:00:00Z",
                    "- updated_at: 2026-06-22T20:00:00Z",
                    "- source_thought_paths: 04-inbox/thought-box/test123.md",
                    "",
                    "## Source Ideas",
                    "- Test123.",
                    "- Test123.",
                    "",
                    "## Source Idea Summaries",
                    "- Test123.",
                    "- Test123.",
                    "",
                    "## Proposed Work",
                    "- Test123.",
                    "- Test123.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        record = viewer_app._parse_proposed_sprint_record(path)
        self.assertEqual(record["idea_count"], 1)
        self.assertEqual(record["canonical_source_ideas"], ["Test123."])

    def test_confirmation_routes_require_post(self) -> None:
        self._create_sprint_record("approved")
        response = self._client().get("/sprints/sp-20260620120000-approved/action")
        self.assertEqual(response.status_code, 405)

    def test_completion_update_by_code_works(self) -> None:
        self._create_sprint_record("approved")
        client = self._client()
        response = client.post(
            "/sprints/code/IMS-SPRINT-20260620-001/action",
            data={"confirm": "yes", "action": "complete", "completion_notes": "Validated in browser."},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        record = viewer_app._sprint_record_by_code("IMS-SPRINT-20260620-001")
        self.assertIsNotNone(record)
        self.assertEqual(record["status_key"], "completed")
        text = (self.root / record["path"]).read_text(encoding="utf-8")
        self.assertIn("Validated in browser.", text)
        self.assertIn("- internal_release_notes:", text)
        self.assertIn("- plain_english_release_notes:", text)

    def test_mark_complete_generates_release_notes_when_missing(self) -> None:
        self._create_sprint_record("approved", title="Worklog Sprint", app_product="Worklog")
        client = self._client()
        response = client.post(
            "/sprints/sp-20260620120000-approved/action",
            data={"action": "complete"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertIsNotNone(record)
        self.assertEqual(record["status_key"], "completed")
        path = self.root / record["path"]
        text = path.read_text(encoding="utf-8")
        self.assertIn("- internal_release_notes:", text)
        self.assertIn("- plain_english_release_notes:", text)
        self.assertIn("Draft release notes generated. Please review before shipping.", response.get_data(as_text=True))
        html = client.get(f"/sprints/{record['id']}").get_data(as_text=True)
        self.assertIn("Internal Release Notes", html)
        self.assertIn("Plain English Release Notes", html)

    def test_existing_release_notes_are_preserved_on_complete(self) -> None:
        path = self._create_sprint_record("approved", title="Worklog Sprint", app_product="Worklog")
        viewer_app._update_sprint_record_text(
            path,
            {
                "internal_release_notes": "Existing internal note.",
                "plain_english_release_notes": "Existing plain note.",
            },
        )
        client = self._client()
        response = client.post("/sprints/sp-20260620120000-approved/action", data={"action": "complete"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        record = viewer_app._sprint_record_by_id("sp-20260620120000-approved")
        self.assertIsNotNone(record)
        updated = (self.root / record["path"]).read_text(encoding="utf-8")
        self.assertIn("Existing internal note.", updated)
        self.assertIn("Existing plain note.", updated)
        self.assertNotIn("Draft release notes generated. Please review before shipping.", response.get_data(as_text=True))

    def test_approval_creates_sprint_record_and_handoff(self) -> None:
        preview = viewer_app._digest_preview(viewer_app._thought_box_items(digested_only=False))
        response = self._client().post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["created_proposed_sprints"])
        self.assertTrue(list((self.root / "06-sprints/proposed").glob("*.md")))
        self.assertTrue(list((self.root / "04-inbox/thought-box/proposed").glob("*.md")))
        record = viewer_app._proposed_sprint_records()[0]
        self.assertTrue(record["source_thought_paths"])
        self.assertTrue(record.get("source_ideas"))
        text = (self.root / record["path"]).read_text(encoding="utf-8")
        self.assertIn("Completion Requirement", text)
        self.assertIn("Source Ideas", text)
        self.assertIn("Sprint Code", text)
        self.assertIn("Codex/ChatGPT Starting Prompt", text)
        self.assertNotIn("No handoff content found. Regenerate handoff.", text)

    def test_initial_and_regenerated_handoffs_match(self) -> None:
        preview = viewer_app._digest_preview(viewer_app._thought_box_items(digested_only=False))
        client = self._client()
        created = client.post("/api/assistant/create-proposed-sprints", json={"digest_preview": preview, "action": "accept_suggested"})
        self.assertEqual(created.status_code, 200)
        proposal = viewer_app._proposed_sprint_records()[0]
        approved = client.post(f"/sprints/{proposal['id']}/action", data={"action": "approve"}, follow_redirects=True)
        self.assertEqual(approved.status_code, 200)
        sprint_record = viewer_app._sprint_records()[0]
        handoff_path = self.root / sprint_record["handoff_path"]
        initial_text = handoff_path.read_text(encoding="utf-8")
        regenerated = client.post(f"/sprints/{sprint_record['id']}/action", data={"action": "regenerate_handoff"}, follow_redirects=True)
        self.assertEqual(regenerated.status_code, 200)
        regenerated_text = handoff_path.read_text(encoding="utf-8")
        self.assertEqual(initial_text, regenerated_text)
        self.assertIn("## Source Ideas", regenerated_text)
        self.assertIn("## Proposed Work", regenerated_text)
        self.assertIn("## Codex/ChatGPT Starting Prompt", regenerated_text)
        self.assertNotIn("No handoff content found. Regenerate handoff.", regenerated_text)

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
