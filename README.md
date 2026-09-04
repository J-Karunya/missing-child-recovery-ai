# Missing Child Recovery AI

> **Prototype/research use only.** This project creates **potential matches** that require authorized human verification. It never confirms that a missing child has been found and is not a live-tracking or public face-search system.

## Purpose

This Python prototype processes an authorized CCTV video for one configured missing-child case. It preserves a simple, local-first pipeline:

```text
Child profile + authorized photo -> InsightFace embedding
Authorized CCTV -> YOLO person detection -> DeepSORT tracks -> InsightFace face comparison
                         -> potential-match evidence -> PENDING human review
```

The current colour-CCTV attribute extractor is deliberately basic. Its output is only supporting evidence and it does not infer attributes the parent did not provide.

## Sprint status

- **Sprint 1 — child profile and embedding foundation:** stabilized. Profiles use a consistent schema; embeddings are validated, normalized, and written atomically as `<child_id>.npy`.
- **Sprint 2 — CCTV potential-match pipeline:** stabilized. YOLO, DeepSORT, and InsightFace remain in place; match events are deduplicated per child/track/run and logged as `PENDING` potential matches.
- **Sprint 3 — context understanding and intelligent matching:** implemented. Optional LLM profile extraction, true/false/null attributes, explainable component scores, multi-frame evidence aggregation, and PENDING evidence metadata are now included.
- **Sprint 4 — authorized review and case-management foundation:** implemented. SQLite-backed cases, PENDING-match review actions, evidence references, local prototype roles, audit records, restricted parent views, and a Streamlit demonstration dashboard are included. Production authentication, notifications, live CCTV, and cloud deployment remain out of scope.

## Layout

```text
data/
  child_images/        # authorized reference photographs (not committed)
  child_profiles/      # raw parent/police case profile
  parsed_profiles/     # structured LLM-derived attributes
  cctv_videos/         # authorized footage (not committed)
  alerts/              # generated evidence images (not committed)
  logs/match_events.csv
embeddings/            # generated biometric vectors (not committed)
services/
tests/
dashboard/              # Streamlit presentation layer; no AI inference logic
```

## Setup

Use Python 3.10+ in a new virtual environment. The ZIP's existing `venv` may not work on another computer because virtual environments contain machine-specific interpreter paths.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Set `OPENAI_API_KEY` in your terminal or operating-system environment only if using the optional LLM profile parser (for PowerShell: `$env:OPENAI_API_KEY="..."`). `.env.example` documents the supported variable names; this lightweight prototype does not load `.env` automatically. Do not commit `.env`, images, CCTV footage, embeddings, or generated evidence.

## Profile understanding

`services/profile_parser.py` uses an optional OpenAI Structured Outputs provider configured through `OPENAI_API_KEY`; it requests a fixed JSON schema instead of performing regex extraction.

If no AI service is configured or it fails, the parser records every uncertain attribute as `null` rather than guessing. Unit tests provide mocked provider responses, so they never require an API key.

Boolean values mean:

- `true`: the parent explicitly confirmed the attribute is present.
- `false`: the parent explicitly confirmed it is absent.
- `null`: the parent did not know, did not mention it, or the AI parser was unavailable.

Unknown values do not count as a mismatch during scoring.

To create/update the structured profile after configuring the LLM:

```powershell
python services/profile_builder.py
```

## Configure the prototype case

`data/child_profiles/MC001.json` identifies the reference image with `image_filename`. The active profile ID defaults to `MC001`; change it only through `MISSING_CHILD_ID`. CCTV input defaults to `station.mp4`; change it through `CCTV_VIDEO_FILE`.

Only simple filenames are accepted for media configuration, preventing configuration values from traversing outside controlled project directories.

## Run the stabilized pipeline

From the project root:

```powershell
python services/generate_embedding.py
python services/cctv_matcher.py
```

Expected embedding output resembles:

```text
Generating embedding for child ID: MC001
Embedding saved safely: ...\embeddings\MC001.npy
Embedding shape: (512,)
```

Expected matching output begins with:

```text
Monitoring child ID: MC001
All results are potential matches pending authorized human verification.
```

For each track with at least three observations and an aggregated score at or above the prototype threshold, it prints `Potential Match Detected` and writes one evidence image, JSON evidence metadata, and one `PENDING` CSV event for that child/track in that run. It does not announce that the child was found.

## Test

```powershell
python -m unittest discover -s tests -v
```

Expected result: passing offline unit tests covering schema consistency, negative/present/unknown attributes through mocked LLM responses, explainable unknown/mismatch scoring, embedding-file validation, and multi-frame aggregation.

## Sprint 4 dashboard

Install requirements, then run:

```powershell
streamlit run app.py
```

The local dashboard initializes `data/database/missing_child_ai.db`. Its selector uses demo identities solely to demonstrate intended ADMIN, POLICE, REVIEWER, and PARENT permissions. It is not a login system and must not be used as production authentication. See [SPRINT_4.md](docs/SPRINT_4.md).

## Known limitations

- Scores are uncalibrated prototype evidence, not probabilities or identification proof.
- The current extractor observes only a coarse top-colour signal; advanced visual attributes and day/night enhancement are future work.
- Sprint 4 SQLite/audit/dashboard features are local prototype foundations, not production authentication, encryption, retention automation, or secure evidence hosting.
- Only authorized, case-associated footage should be processed. Protect all biometric material and evidence under applicable law and policy.
