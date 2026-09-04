import tempfile
import unittest
from pathlib import Path

from services.detector import MIN_VALID_MODEL_BYTES, model_file_status


class DetectorFileValidationTests(unittest.TestCase):
    def test_missing_model_is_reported_without_a_download(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(model_file_status(Path(directory) / "yolov8n.pt"), "is missing")

    def test_empty_model_is_rejected_before_ultralytics_loads_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "yolov8n.pt"
            path.touch()
            self.assertIn("too small (0 bytes", model_file_status(path))

    def test_large_enough_file_passes_the_lightweight_file_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "yolov8n.pt"
            path.write_bytes(b"0" * MIN_VALID_MODEL_BYTES)
            self.assertIsNone(model_file_status(path))
