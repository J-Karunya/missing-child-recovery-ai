# Sprint 2 — CCTV Potential-Match Pipeline

## IMPLEMENTED NOW

Sprint 2 connected the existing reference embedding to authorized CCTV processing. YOLO detects people efficiently, DeepSORT keeps a person’s identity stable between frames, and InsightFace compares detected faces with the child embedding. Parsed child profiles and a first conservative attribute signal supported matching. Events are logged with controlled evidence images and **Potential Match** semantics: every result is `PENDING`, never “child found.”

Key files are `services/detector.py`, `services/tracker.py`, `services/cctv_matcher.py`, `services/profile_parser.py`, `services/profile_builder.py`, `services/attribute_extractor.py`, `services/match_engine.py`, and the offline tests. Security foundations include environment-variable secrets, filename validation, controlled paths, ignored sensitive artifacts, and no API keys in code.

Run the pipeline after creating a profile and embedding:

```powershell
python services/profile_builder.py
python services/generate_embedding.py
python services/cctv_matcher.py
```

## PLANNED FUTURE

Sprint 2 did not include temporal aggregation, rich explainable components, dashboards, authentication, live streams, or multi-camera deployment. Sprint 3 adds the first two only.
