# Run Guide

## IMPLEMENTED NOW

Use Python 3.10+ from the project root.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Create `data/child_profiles/MC001.json` with basic case information and an `image_filename`; place that authorized image under `data/child_images`. To enable optional LLM profile understanding, set the API key in the active PowerShell session (the `.env.example` file documents supported names; this prototype does not auto-load `.env`). Without a key, parsing still completes with unknown attributes.

```powershell
$env:OPENAI_API_KEY="your-key"
```

```powershell
python services/profile_builder.py
python services/generate_embedding.py
python services/detector.py --download
python services/detector.py
python services/cctv_matcher.py
streamlit run app.py
```

`detector.py --download` uses Ultralytics' supported `YOLO("yolov8n.pt")` mechanism to retrieve the official small YOLOv8n weight file, validates it, and stores it at `models/yolov8n.pt`. It downloads into a temporary directory first, so an interrupted download does not leave a partial project model. The matcher can also perform this recovery automatically when the configured model is missing or too small. Internet access is required only for that recovery step.

Expected output: profile builder prints the parsed-profile path; embedding generation prints `Embedding saved safely` and normally `(512,)`; matcher prints the child ID and says every result is pending human verification. If a qualified multi-frame track passes the threshold, it prints `Potential Match Detected`, saves one JPEG and JSON metadata in `data/alerts`, and logs a PENDING row in `data/logs/match_events.csv`.

The matcher prints progress every 30 frames by default, followed by a summary with the run ID, frame count, observed tracks, tracks with faces, potential matches, and evidence-file count. Configure `CCTV_VIDEO_FILE` to another simple filename such as `street.mp4` after placing that authorized file under `data/cctv_videos`; source-code changes are not needed. `MAX_CCTV_VIDEO_BYTES`, `CCTV_PROGRESS_INTERVAL`, `MIN_TRACK_OBSERVATIONS`, and the evidence-retention preparation value are also configurable through environment variables.

`streamlit run app.py` initializes the local SQLite database at `data/database/missing_child_ai.db` and opens the authenticated review dashboard. Cases are created by police/admin roles; only PENDING potential matches can be reviewed; and a VERIFY decision requires explicit confirmation. The controlled CCTV-submission page accepts only MP4, AVI, or MOV and stores the file as `PENDING_PROCESSING` without running it automatically.

## Sprint 5 secure login

Sprint 5 replaces the demo identity selector with Argon2 password login. Before the first dashboard start, set a local bootstrap-admin account in the terminal; do not commit these values:

```powershell
$env:BOOTSTRAP_ADMIN_USERNAME="admin"
$env:BOOTSTRAP_ADMIN_EMAIL="admin@example.org"
$env:BOOTSTRAP_ADMIN_PASSWORD="choose-a-unique-password-of-at-least-12-characters"
streamlit run app.py
```

For a development-only role demonstration, set `DEMO_USER_PASSWORD` and run `python scripts/create_demo_users.py`. The script is explicit, never runs at application startup, and never prints a password. See [AUTHENTICATION.md](AUTHENTICATION.md) and [PRIVACY_AND_RETENTION.md](PRIVACY_AND_RETENTION.md). The dashboard remains a secured prototype: it is not production-ready without MFA, HTTPS, secure deployment, and formal security/privacy review.

## Sprint 6 notification centre

After sign-in, open **Notifications** in the same dashboard. It shows only records authorized for the signed-in account; a parent sees parent-safe wording, and staff see their station-authorized operational detail. Select **Mark as read** to record the read timestamp. On the case page, ADMIN/POLICE can manage active/pending/closed station assignments; only the original and active assigned stations receive future staff notifications.

The default delivery is local SQLite/in-app only. It does not send SMS, email, WhatsApp, or push notifications and needs no external credentials. A camera observation is displayed internally as **Last observed camera**, not live GPS.

Common issues:

- **PowerShell blocks activation:** run `Set-ExecutionPolicy -Scope Process Bypass`, then activate again.
- **No face detected:** use a clearer authorized reference photograph with one visible face.
- **Parsed profile missing:** run `python services/profile_builder.py` first.
- **Embedding missing/invalid:** run `python services/generate_embedding.py` again.
- **YOLO model/video missing:** check `models/yolov8n.pt` and the simple filename in `.env` under `data/cctv_videos`.
- **`EOFError: Ran out of input`:** the `.pt` file is empty or incomplete. Run `python services/detector.py --download`, then verify with `python services/detector.py` (it prints `YOLO MODEL OK`).
- **LLM unavailable:** this is safe; attributes become `null`. Check `OPENAI_API_KEY` only if you need extraction.
- **No potential match:** this is a normal result; it is not an error or a claim that the child is absent.

## PLANNED FUTURE

There is no dashboard, login, live stream, public upload, notification, database migration, or cloud deployment command yet.
# Sprint 12 workflow note

For a parent report, use the Cases page to submit the child details and recent
photo. The report stays pending police verification. An authorized police or
admin account records the complaint/reference verification before the case can
be active for CCTV processing. A configured age-progression provider is needed
to create a candidate; no provider is bundled with this research prototype.

## Sprint 13 UI demo preparation

Set a development-only demo password and a Fernet evidence key before starting
the app. Then use either the Admin **Demo Setup** page or the explicit script:

```powershell
$env:DEMO_SETUP_PASSWORD="choose-a-unique-development-password"
$env:EVIDENCE_ENCRYPTION_KEY="your-fernet-key"
python scripts/demo_setup.py --apply
streamlit run app.py
```

The script preserves existing demo credentials. Parent uploads use controlled
encrypted storage, so photo upload correctly fails closed if the encryption key
is absent. A real/sample authorized CCTV video is still required to run the
existing pipeline; no match is fabricated when there is no usable video, model,
or face result.
