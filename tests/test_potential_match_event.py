import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.utils import log_potential_match


class PotentialMatchEventTests(unittest.TestCase):
    def test_event_is_logged_as_pending_with_explainable_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            logs_dir = Path(directory)
            with patch("services.utils.LOGS_DIR", logs_dir), patch("services.utils.ensure_runtime_directories"):
                path = log_potential_match({
                    "run_id": "run-123", "child_id": "MC001", "track_id": 12, "frame_number": 120,
                    "face_score": 82, "overall_score": 80, "status": "PENDING",
                    "verification_status": "PENDING", "matched_attributes": ["clothing.top_color"],
                    "evidence_reasons": {"matched": ["clothing.top_color"]},
                })
            with path.open(newline="", encoding="utf-8") as file:
                row = next(csv.DictReader(file))
            self.assertEqual(row["status"], "PENDING")
            self.assertEqual(row["run_id"], "run-123")
            self.assertEqual(row["verification_status"], "PENDING")
            self.assertEqual(row["matched_attributes"], "clothing.top_color")
