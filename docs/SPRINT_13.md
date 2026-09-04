# Sprint 13 — End-to-End Demo UI Integration

## Objective

Make the entire project demonstrable through the Streamlit UI without manually
executing Python pipeline scripts. The existing Sprint 1–12 implementation is
preserved unchanged; Sprint 13 adds only a thin orchestration layer and UI
improvements.

## AI Decision Chain — Unchanged

```
YOLO detection
    ↓
DeepSORT tracking
    ↓
InsightFace face comparison
    ↓
Attribute + temporal evidence aggregation
    ↓
PENDING potential match (AI result — never a final decision)
    ↓
Authorized human REVIEWER: VERIFY or REJECT
```

**AI never automatically declares a child found.**

---

## What Was Added

### `services/pipeline_service.py` [NEW]

A thin orchestration wrapper that exposes the existing `run_matcher()` pipeline
as a callable service function. It does not contain any AI logic. It:

1. Validates that the case is ACTIVE (calls `store.case_allows_ai_processing()`)
2. Locates the uploaded video in `CCTV_UPLOADS_DIR`
3. Generates a child face embedding if one does not already exist
4. Copies the video temporarily to `CCTV_VIDEOS_DIR` (required by `run_matcher()`)
5. Calls the existing `run_matcher(child_id, cctv_filename)` unchanged
6. Cleans up the temporary copy
7. Returns a structured result with match count

The existing AI pipeline semantics (YOLO model, DeepSORT behavior, InsightFace
model, cosine similarity, attribute comparison, temporal aggregation, thresholds,
PENDING status) are completely unchanged.

### `dashboard/police_view.py` [NEW]

Police-specific dashboard with three tabs:

- **Pending Complaints** — lists cases with `PENDING_POLICE_VERIFICATION` status.
  Shows child details, complaint information, and a Verify form that calls
  `store.verify_police_complaint()`.
- **CCTV Analysis** — CCTV upload form for ACTIVE cases + list of stored
  submissions with a **Run AI Analysis** button that calls `pipeline_service.run_cctv_analysis()`.
- **Potential Matches** — summary view of PENDING/reviewed matches.

### `dashboard/admin_view.py` [NEW]

Admin overview with eight tabs:

- Summary, Users, Cases, Matches, Notifications, Evidence Lifecycle, Audit Logs,
  System Health.

All tabs are read-only and call existing service methods. No admin UI change
bypasses service-layer authorization.

### `dashboard/age_progression_view.py` [NEW]

Age progression initiation and review page for POLICE/REVIEWER:

- Shows the configured provider status prominently (NOT CONFIGURED / DEVELOPMENT
  PLACEHOLDER / real provider name).
- Allows requesting a candidate → always starts `PENDING_REVIEW`.
- Lists pending candidates for reviewer approval/rejection.
- Development placeholder is always explicitly labeled as non-predictive.

### `dashboard/demo_setup.py` [NEW]

Development-only demo account setup page:

- Only shown when `APP_ENV=DEVELOPMENT` (the default).
- Reads password from `DEMO_SETUP_PASSWORD` env var — never printed or logged.
- Creates: `parent_demo`, `police_demo`, `reviewer_demo`, `admin_demo`.
- Contains the full 17-step demo walkthrough inside the app.

### `app.py` [MODIFIED — additive only]

- Added role-aware navigation:
  - `PARENT` sees: Dashboard, My Cases, Notifications, Profile, About System
  - `POLICE` sees: Dashboard, Police Dashboard, Cases, Potential Matches,
    Notifications, Evidence, Age Progression, Profile, About System
  - `REVIEWER` sees: Dashboard, Potential Matches, Evidence, Age Progression,
    Notifications, Profile, About System
  - `ADMIN` sees: everything including Admin Overview, Demo Setup
- Added role-specific dashboard landing pages
- Added routing for all new pages
- All existing page routes preserved

### `tests/test_sprint13_demo_flow.py` [NEW]

34 new unit/integration tests covering:
- Parent report workflow (6 tests)
- Police workflow (6 tests)
- CCTV upload validation (4 tests)
- Reviewer workflow (6 tests)
- Age progression lifecycle (5 tests)
- Pipeline service validation (3 tests)
- Role isolation regression (4 tests)

---

## Demo Setup

### Prerequisites

1. Install requirements: `pip install -r requirements.txt`
2. Set environment variables in `.env`:

```env
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_EMAIL=admin@demo.local
BOOTSTRAP_ADMIN_PASSWORD=YourAdminPass123
DEMO_SETUP_PASSWORD=YourDemoPass123
APP_ENV=DEVELOPMENT
```

3. Start the app: `streamlit run app.py`
4. Log in as admin → go to **Demo Setup** → click **Create / Verify All Demo Accounts**

### Demo Accounts

| Role | Username | Notes |
|---|---|---|
| PARENT | `parent_demo` | Can submit reports, upload photos |
| POLICE | `police_demo` | Can verify complaints, upload/run CCTV |
| REVIEWER | `reviewer_demo` | Can VERIFY/REJECT potential matches |
| ADMIN | `admin_demo` | Full system overview |

Password for all demo accounts: the value of `DEMO_SETUP_PASSWORD`.

The dashboard setup page, or the explicit command below, creates only missing
accounts and initializes only passwordless demo accounts. It never replaces an
existing demo password:

```powershell
$env:DEMO_SETUP_PASSWORD="choose-a-unique-development-password"
python scripts/demo_setup.py --apply
```

Controlled child and parent/guardian photo uploads require an
`EVIDENCE_ENCRYPTION_KEY`. Keep that key in the environment or a local ignored
configuration source; do not enter it in the application or store it in SQLite.

---

## 17-Step Demo Flow

```
1.  Login as parent_demo (PARENT)
2.  Cases → Register Missing Child Case → fill form → upload child photo → Submit
3.  Cases → Upload Recent Parent/Guardian Reference Photo → upload
4.  Confirm status: PENDING_POLICE_VERIFICATION
5.  Logout
6.  Login as police_demo (POLICE)
7.  Police Dashboard → Pending Complaints → find case → fill verification form
8.  Click Verify and Activate Case → status becomes ACTIVE
9.  Police Dashboard → CCTV Analysis → upload CCTV video for the ACTIVE case
10. Click Run AI Analysis → watch YOLO → DeepSORT → InsightFace progress
11. View potential match count (PENDING — not confirmed)
12. Logout
13. Login as reviewer_demo (REVIEWER)
14. Potential Matches → expand a PENDING match → view evidence and scores
15. Click VERIFY (with confirmation checkbox) or REJECT
16. Logout
17. Login as admin_demo (ADMIN) → Admin Overview → Audit Logs → see full trail
```

---

## Unchanged AI Safety Rule

Authorized CCTV → YOLO → DeepSORT → InsightFace → attributes → temporal and
explainable evidence → `PENDING` potential match → authorized human `VERIFY`/`REJECT`.

AI never declares a child found, closes a case, or performs a final review
decision.
