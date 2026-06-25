from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import app as viewer_app


class ReleaseViewerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "03-releases").mkdir(parents=True, exist_ok=True)
        self.release_path = self.root / "03-releases/ims-warehouse-foundation-release-1-0.md"
        self.release_path.write_text(
            "\n".join(
                [
                    "# IMS Warehouse Foundation Release 1.0",
                    "",
                    "## Release Metadata",
                    "",
                    "- Release ID: IMS-WF-R1",
                    "- Release Name: IMS Warehouse Foundation Release 1.0",
                    "- Application: IMS",
                    "- Program: Warehouse Modernization",
                    "- Marathon: Enterprise Shipment Management",
                    "- Run: Enterprise Shipment Management",
                    "- Track: Warehouse Foundation",
                    "- Version: 1.0",
                    "- Status: Release Candidate",
                    "",
                    "## Scope",
                    "",
                    "Warehouse Foundation Release 1.0 packages the completed warehouse foundation work into a single operational delivery milestone.",
                    "",
                    "## Included Sprints",
                    "",
                    "- Internal Pallet IDs",
                    "- Break Bulk Foundation",
                    "- Break Bulk Intake Wizard",
                    "",
                    "## Included Validation Sessions",
                    "",
                    "- IMS Warehouse Foundation Release 1.0 Validation",
                    "",
                    "## Release Notes",
                    "",
                    "- Release notes will be drafted from the completed sprint records and validation findings.",
                    "",
                    "## Known Issues",
                    "",
                    "- QR code printable area",
                    "- Print preview modal",
                    "- Audit breadcrumb improvement",
                    "",
                    "## Deferred Items",
                    "",
                    "- Define business rule when `pallet_equivalent_qty > 1.0`",
                    "",
                    "## Release Health",
                    "",
                    "- P0 count: 0",
                    "- P1 count: 0",
                    "- P2 count: 1",
                    "- P3 count: 0",
                    "- Idea count: 0",
                    "",
                    "## Validation Coverage",
                    "",
                    "- 96%",
                    "",
                    "## Release Confidence",
                    "",
                    "Conditionally Ready",
                    "",
                    "## Go / No-Go Recommendation",
                    "",
                    "Go pending resolution of the P2 presentation issue and the business-rule decision.",
                    "",
                    "## Production Rollout Plan",
                    "",
                    "1. Validate the release candidate in DEV.",
                    "2. Resolve the remaining presentation issue.",
                    "3. Confirm the warehouse business rule.",
                    "4. Promote to staging and then production.",
                    "",
                    "## Rollback Plan",
                    "",
                    "Revert to the previous shipped warehouse baseline if validation or rollout surfaces a blocking issue.",
                    "",
                    "## Validation Session Notes",
                    "",
                    "The validation session is the source of readiness evidence for this release.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.old_root = viewer_app.WORKLOG_ROOT
        viewer_app.WORKLOG_ROOT = self.root

    def tearDown(self) -> None:
        viewer_app.WORKLOG_ROOT = self.old_root
        self.tmp.cleanup()

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

    def test_release_discovery_returns_record(self) -> None:
        records = viewer_app._release_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["release_name"], "IMS Warehouse Foundation Release 1.0")
        self.assertEqual(records[0]["application"], "IMS")
        self.assertEqual(records[0]["status"], "Release Candidate")
        self.assertEqual(records[0]["validation_coverage"], "96%")

    def test_releases_list_renders(self) -> None:
        html = self._client().get("/releases").get_data(as_text=True)
        self.assertIn("Releases", html)
        self.assertIn("IMS Warehouse Foundation Release 1.0", html)
        self.assertIn("Release Candidate", html)
        self.assertIn("Validation 96%", html)
        self.assertIn(">Releases<", html)
        self.assertIn('href="/releases"', html)

    def test_release_detail_renders(self) -> None:
        html = self._client().get("/releases/ims-warehouse-foundation-release-1-0").get_data(as_text=True)
        self.assertIn("IMS Warehouse Foundation Release 1.0", html)
        self.assertIn("Warehouse Modernization", html)
        self.assertIn("Enterprise Shipment Management", html)
        self.assertIn("Warehouse Foundation", html)
        self.assertIn("1.0", html)
        self.assertIn("Release Candidate", html)
        self.assertIn("96%", html)
        self.assertIn("Conditionally Ready", html)
        self.assertIn("Go pending resolution of the P2 presentation issue and the business-rule decision.", html)
        self.assertIn("Internal Pallet IDs", html)
        self.assertIn("IMS Warehouse Foundation Release 1.0 Validation", html)
        self.assertIn('href="/releases"', html)

if __name__ == "__main__":
    unittest.main()
