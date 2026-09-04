import tempfile
import unittest
from pathlib import Path

import numpy as np

from services.utils import load_embedding_file


class EmbeddingValidationTests(unittest.TestCase):
    def test_empty_embedding_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MC001.npy"
            path.touch()
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                load_embedding_file(path)

    def test_missing_embedding_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "missing or empty"):
                load_embedding_file(Path(directory) / "MC001.npy")

    def test_non_finite_embedding_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MC001.npy"
            np.save(path, np.array([1.0, np.nan], dtype=np.float32))
            with self.assertRaisesRegex(ValueError, "invalid"):
                load_embedding_file(path)

    def test_valid_embedding_is_normalized_for_cosine_similarity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MC001.npy"
            np.save(path, np.array([3.0, 4.0], dtype=np.float32))
            self.assertAlmostEqual(float(np.linalg.norm(load_embedding_file(path))), 1.0)

    def test_valid_embedding_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "MC001.npy"
            np.save(path, np.array([0.25, 0.75], dtype=np.float32))
            loaded = load_embedding_file(path)
            self.assertEqual(loaded.shape, (2,))
