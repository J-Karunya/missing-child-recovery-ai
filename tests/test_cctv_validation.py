import unittest

import numpy as np

from services.cctv_matcher import run_matcher
from services.lighting_detector import classify_lighting


class CctvValidationTests(unittest.TestCase):
    def test_missing_cctv_file_has_actionable_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "CCTV video not found"):
            run_matcher(cctv_filename="missing-video.mp4")

    def test_path_traversal_is_rejected_before_processing(self):
        with self.assertRaisesRegex(ValueError, "simple filename"):
            run_matcher(cctv_filename="../station.mp4")

    def test_day_night_label_accepts_colour_and_grayscale(self):
        self.assertEqual(classify_lighting(np.full((4, 4, 3), 180, dtype=np.uint8)), "DAY")
        self.assertEqual(classify_lighting(np.full((4, 4), 20, dtype=np.uint8)), "NIGHT")
