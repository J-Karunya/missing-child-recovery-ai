# Sprint 1 — Profile and Embedding Foundation

## IMPLEMENTED NOW

Sprint 1 established a safe, understandable local case foundation: raw child profiles, controlled project-relative paths, child-image validation, InsightFace embedding generation, normalized `.npy` output, and embedding-file validation. Its objective was to create reusable facial reference data, not make match decisions.

Important files: `services/config.py`, `services/generate_embedding.py`, `services/utils.py`, `data/child_profiles/MC001.json`, and `tests/test_embedding_validation.py`. Technologies are Python, OpenCV, NumPy, and InsightFace/ArcFace.

Workflow: create the JSON profile with a simple image filename, place an authorized image in `data/child_images`, then run:

```powershell
python services/generate_embedding.py
```

Expected output identifies the child ID, safe embedding path, and vector shape (normally `(512,)`). Embeddings are normalized because cosine similarity compares vector direction consistently. Project-relative paths make the project portable and reduce accidental access outside controlled folders. Limitations: one image/reference embedding per case, no age progression, and no database.

## PLANNED FUTURE

Multiple reference photos, supervised image-upload workflows, encrypted biometric storage, and age progression are future work.
