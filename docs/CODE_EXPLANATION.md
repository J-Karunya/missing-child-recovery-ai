# Code Explanation

## IMPLEMENTED NOW

| File | Why it exists; receives; does; returns/connects |
|---|---|
| `generate_embedding.py` | Creates the child’s reusable face reference. It receives the active child ID and raw profile/image; validates them, asks InsightFace for the largest detected face, normalizes the vector, and saves it atomically. It returns path and shape to the caller; `cctv_matcher.py` later loads this embedding. |
| `detector.py` | Isolates YOLO setup from application logic. A `.pt` file contains trained YOLO weights, so it is required before YOLO can recognize people. `model_file_status()` rejects missing or suspiciously small local files before PyTorch attempts to load them. `download_official_model()` uses the supported Ultralytics loader to obtain official `yolov8n.pt` in a temporary folder, validates it, and safely places it in `models/`. `get_detector()` returns a YOLO detector. When the matcher calls that detector with a CCTV frame, YOLO returns person bounding boxes; `cctv_matcher.py` sends those boxes to DeepSORT, which turns them into stable track IDs. |
| `tracker.py` | Keeps tracking configuration small and readable. It receives no data at construction and returns a DeepSORT tracker; the matcher gives it detections every frame and receives stable track IDs. |
| `cctv_matcher.py` | Is the pipeline coordinator. It receives child ID and video filename, validates files, detects/tracks people, compares faces, extracts attributes, aggregates track evidence, and saves PENDING results. It returns the potential-match count. `run_matcher()` is its important function. |
| `profile_builder.py` | Makes a durable parsed profile from the raw case JSON. It receives a profile and optional parser provider, validates required fields, calls `parse_description()`, and returns/saves a structured profile. |
| `profile_parser.py` | Prevents free-text descriptions from spreading through the rest of the system. It receives description text and an optional provider, uses structured LLM output when configured, normalizes values, and returns the fixed schema. `unknown_attributes()` and `normalize_attributes()` make uncertain data safely `null`. |
| `attribute_extractor.py` | Separates visual observations from matching policy. It receives a person crop and returns the nullable attribute schema. `dominant_color()` and `classify_bgr()` currently provide only coarse top colour; unsupported attributes remain `null`. |
| `match_engine.py` | Explains matching rather than hiding it in one number. It receives face similarity, expected profile attributes, and observed attributes; `build_match_scores()` returns component scores, overall score, and matched/mismatched/unknown lists. It connects profile understanding with temporal aggregation. |
| `temporal_evidence.py` | Makes one-frame results less fragile. It receives a track ID, score result, and frame number; `TrackEvidenceAggregator.add()` returns averaged scores, best frame, evidence lists, observation count, and readiness. |
| `utils.py` | Centralizes low-level safety checks. It receives an embedding path or event dictionary; validates/loads the embedding or appends a fixed-column CSV event. Both embedding generation and matching use it. |
| `config.py` | Defines controlled, project-relative locations and adjustable prototype settings. It receives environment variables and returns safe paths/settings. `safe_filename()` blocks path traversal. |
| `notification_service.py` | Receives an existing PENDING/VERIFIED/REJECTED match ID and returns deduplicated local notification records. It centralizes parent-safe and staff templates, selects only the linked parent and original/active assigned stations, and uses a database-only provider by default. |

The modules are intentionally separate so a future attribute model, dashboard, or storage system can change one part without rewriting detection, tracking, or scoring.

## Step-by-step pipeline for beginners

1. `profile_builder.py` checks that the case has a child ID, name, and description. Its optional LLM provider turns only explicitly stated details into structured data. For example, glasses can be `true`, `false`, or `null`; `null` means the system does not know.
2. `generate_embedding.py` reads the authorized reference image and asks InsightFace to create a 512-number face representation. It normalizes that vector so cosine similarity compares direction fairly.
3. `detector.py` loads the small official YOLO model. YOLO is selected because it finds people quickly in ordinary video frames. It returns person bounding boxes, not identities.
4. `tracker.py` gives those boxes to DeepSORT. DeepSORT assigns a stable track ID, so the same person in several frames is treated as one candidate instead of several unrelated detections.
5. `cctv_matcher.py` crops each confirmed tracked person and asks InsightFace whether a face is visible. A candidate face embedding is normalized and compared with the child embedding using cosine similarity.
6. `attribute_extractor.py` provides only cautious supporting observations. At present that means coarse clothing top colour; it deliberately leaves unsupported details as `null`.
7. `match_engine.py` combines available face and attribute evidence into separate scores and an explainable overall score. Missing information is excluded rather than treated as a mismatch.
8. `temporal_evidence.py` averages several observations for one DeepSORT track. This is why one accidental frame cannot create an event.
9. When a track crosses the configurable threshold after the required observations, the matcher saves an evidence frame, JSON explanation, structured PENDING event, and minimal audit record. It never declares a child found.

## Inputs, outputs, and limitations

Every major module has one narrow job: configuration supplies safe project-relative paths; profile parsing produces nullable structured context; embedding generation produces a normalized vector; detection produces boxes; tracking produces IDs; face analysis produces candidate vectors; scoring produces reasons; and the matcher writes controlled evidence. This separation makes the project easier to test and explain.

The chosen technologies solve different problems: YOLO is an efficient person detector, DeepSORT adds time consistency, InsightFace provides practical face embeddings, cosine similarity compares normalized vectors, and the optional LLM understands natural parent language without replacing the strict schema. Limitations remain important: CCTV quality can be poor, visual attributes are currently basic, scores are not calibrated probabilities, and a human reviewer must make the final decision.

## Interview explanation

### 30 seconds

“Missing Child Recovery AI is a local decision-support prototype for authorized CCTV. It creates an InsightFace embedding from a reference photo, uses YOLO to find people and DeepSORT to keep stable track IDs, then compares faces across multiple frames. Parent descriptions are optional structured context, and every result remains a PENDING potential match for human review.”

### 1 minute

“The project avoids relying on a single frame. YOLO finds people, DeepSORT tracks each person, and InsightFace compares a detected face with the reference embedding through cosine similarity. I add conservative profile evidence such as clothing colour only when it is known. Unknown details remain `null`, so they do not become false mismatches. The match engine returns separate face and attribute scores with reasons, and temporal aggregation requires several observations before saving PENDING evidence.”

### 3–5 minutes

Start with the safety goal: the system helps reviewers search authorized footage and never claims a child is found. Then walk through the nine pipeline steps above. Explain that paths are project-relative, extensions and input size are validated, embeddings are finite and normalized, evidence has a run ID, and logs avoid raw vectors. Finish with limitations: current attributes are basic, data is file-based, and production deployment still needs authentication, encryption, review UI, retention workflow, and governance.

### Likely questions and short answers

| Question | Beginner-friendly answer |
|---|---|
| Why YOLO? | It is a fast, well-supported model for locating people in each video frame. |
| Why DeepSORT? | It keeps a consistent ID for the same person across frames, which makes multi-frame evidence possible. |
| Why InsightFace and cosine similarity? | InsightFace creates compact face vectors; cosine similarity compares their direction after normalization. |
| Why not only face recognition? | CCTV faces can be blurred or partly hidden. Clothing/context helps explain evidence, but does not override uncertainty. |
| Why multiple frames? | A single frame is noisy. Several observations reduce one-frame false alerts. |
| Why an LLM for descriptions? | It converts natural language into a fixed schema. If unavailable, the system safely records unknowns instead of guessing. |
| What does `null` mean? | Unknown or not provided—not false. It is excluded from scoring. |
| How are false alerts reduced? | Configurable threshold, temporal aggregation, track deduplication, explainable evidence, and mandatory human verification. |
| How does night footage work? | It is processed normally and labelled DAY/NIGHT; advanced enhancement is deliberately future work. |
| How could live CCTV, Power BI, or many stations fit? | They would be future input, review, and reporting layers around the same detection-to-PENDING pipeline. |
| Why no database yet? | Local files keep the student prototype small and inspectable. Production would use protected case/evidence storage with access controls. |
| How is privacy protected? | Authorized inputs only, no keys in code, controlled paths, ignored sensitive artifacts, minimal logs, and human review. Authentication and encryption remain required before production. |

## Sprint 4: beginner explanation

`review_store.py` is the bridge between the AI result and a human review. It uses SQLite, a small file-based database included with Python, because a student prototype needs reliable tables and relationships without setting up a database server. It receives validated case details or a PENDING potential match, saves them to related tables, checks the selected role, and returns only information that role may see.

The `dashboard/` folder is the presentation layer. Streamlit is selected because it turns Python data into a clear demo interface quickly. `app.py` coordinates navigation and calls the review store; it does **not** run YOLO, DeepSORT, or InsightFace. `case_view.py` handles case forms, `match_view.py` shows explainable scores and review controls, `audit_view.py` shows restricted audit history, and `components.py` centralizes the explicitly labelled local demo-role selector.

RBAC means role-based access control: the application checks whether ADMIN, POLICE, REVIEWER, or PARENT is permitted to perform an action. In this prototype it demonstrates the policy with local identities. It is not secure authentication; a real deployment would require password hashing, MFA, sessions, HTTPS, server-side access enforcement, encryption, and secure secrets.

The complete flow is: reference photo → InsightFace embedding → YOLO person boxes → DeepSORT track IDs → InsightFace/cosine face comparison → optional profile/context data → attribute comparison → multi-frame temporal evidence → PENDING potential match → SQLite evidence/review record → authorized human dashboard decision. KEEP PENDING, VERIFY, and REJECT are human actions. A Verified Match is “verified by an authorized reviewer,” never “verified by AI.”

## PLANNED FUTURE

Further production hardening—MFA, HTTPS, secure server-side sessions, malware scanning, approved retention automation, notifications, live cameras, and role-management operations—is future work.

## Sprint 5: security explanation

`auth.py` solves the password problem. It receives a password only during user creation or login, uses Argon2 to turn it into a one-way hash, and outputs either a safe true/false verification result or a small session dictionary without any password. A hash is selected because a stolen database should not reveal the original password directly.

`review_store.py` is also the authorization boundary. It receives an authenticated user and a requested case, match, evidence item, upload, or review action. It checks the database role, active state, station/case ownership, and allowed transition before producing data or writing a record. For example, a parent receives only their linked case’s parent-safe fields, even if they try to call the service directly.

The login workflow is: username/email and password → generic credential check → temporary lockout after repeated failures → Argon2 verification → user ID stored in Streamlit session state → every page rechecks the user’s active account and session timeout → logout clears state. Login failures and logout are audited without including a password.

`retention.py` receives an administrator request and reports records older than the configured policy windows. It outputs a dry-run report by default. It does not delete evidence unless deletion is explicitly enabled and dry-run has been disabled under an approved policy. This protects against accidental loss of investigation material.

The complete secure flow is: parent/police case → reference photo → embedding → CCTV → YOLO → DeepSORT → InsightFace → explainable score → temporal evidence → PENDING potential match → SQLite → authenticated reviewer → VERIFY/REJECT/KEEP PENDING → audit. AI does not decide a child has been found.

## Sprint 6: notification explanation

Sprint 6 begins only after the pipeline has produced a stored `PENDING` record. `ReviewStore.record_potential_match()` asks the notification service to create local notification rows. The linked parent gets a deliberately cautious message: a potential match is under authorized review. Police and reviewers only receive an internal row when their account station is the original case station or an explicitly active case assignment. The database prevents duplicate rows for the same case, match, recipient, and message type.

When a reviewer chooses VERIFY or REJECT, the same service adds a conservative follow-up. VERIFY is an authorized review result, not an AI declaration that a child has been found. The notification centre lets only its authorized recipient mark a row READ; an administrator can inspect overall records/audits. Every action remains subject to active-account and service-layer authorization checks.

A `match_observations` record can associate a match with an existing camera and time. That lets staff describe the **last observed camera**. It is not live location, live GPS, or a promise that a person is still there. Parents do not receive this operational detail.
