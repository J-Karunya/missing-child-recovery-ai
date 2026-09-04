# Sprint 3 — AI Context Understanding and Intelligent Matching

## IMPLEMENTED NOW

### Objective and problem

Sprint 3 makes a face-similarity candidate more understandable by combining it with optional parent context while avoiding invented evidence. Parents can describe a child naturally; no field is mandatory beyond the existing basic case information.

### Architecture changes and files

`profile_parser.py` provides optional LLM structured extraction and safe all-unknown fallback; `profile_builder.py` saves the parsed profile. `attribute_extractor.py` now returns the full nullable schema even when only top colour is currently observable. `match_engine.py` provides component scores, evidence lists, and configurable weights from `config.py`. New `temporal_evidence.py` averages evidence across a DeepSORT track. `cctv_matcher.py` waits for multiple observations, deduplicates a child/track/run, and writes frame + JSON evidence. `utils.py` logs the expanded event fields. New tests cover mismatch/unknown evidence and multi-frame aggregation.

### Algorithm and score methodology

Face similarity is converted to 0–100. Clothing, accessory, and physical-feature scores average only comparable known values. Weights default to face 70%, clothing 15%, accessories 10%, physical features 5%, and are re-normalized when a component has no usable evidence. `true`, `false`, and `null` are distinct: `false` is an explicit absence; `null` is unknown and never penalizes a candidate. The extractor does not claim to detect bags, glasses, caps, masks, watches, or scars yet—those are returned as `null`.

For each track, three observations are collected by default. Their available component scores are averaged, the best frame is noted, and duplicate potential matches are prevented for the same child + track during a run. A passing record includes IDs, scores, attribute evidence, frame number, UTC timestamp, source, PENDING status, JPEG, and JSON metadata.

### AI role and failure handling

The optional LLM understands natural language into a fixed schema; it is not used to invent visual facts or make a final decision. It uses `OPENAI_API_KEY` from the environment. If unavailable, the parser warns and returns unknown attributes while preserving the raw parent description; mocked providers keep tests offline.

### Tests and limitations

Run `python -m unittest discover -s tests -v`. Tests cover full schema behavior through mocks, partial/unknown/negative attributes, matches/mismatches, face-only scoring, temporal aggregation, PENDING results, and deduplication design. The suite does not call a paid LLM or models.

Limitations: score weights and threshold are prototype values, physical/free-text features are not visually detected, temporal evidence is a simple average, and evidence is not a final identification. Human review remains required.

## PLANNED FUTURE

Potential next steps are calibrated evaluation data, stronger visual-attribute models, review dashboards, authentication/roles, audit and retention controls, notifications, live/multi-camera CCTV, and cloud deployment. These are not Sprint 3 features.

### Execution maintenance note

The existing YOLO execution foundation uses the official small `yolov8n.pt` model at `models/yolov8n.pt`. The loader now rejects empty/suspiciously small files and can recover the official model through Ultralytics without changing the detection architecture. This is a Sprint 3 execution repair, not a new feature.

### Stabilization note

The completed Sprint 3 pipeline now reports bounded frame progress and a run summary, attaches run IDs and explainable reasons to PENDING evidence, validates configured input size/path, and writes minimal audit lifecycle records. A lightweight DAY/NIGHT classifier is metadata only and does not add a new recognition model.
