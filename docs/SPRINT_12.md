# Sprint 12 — Police Verification and Parent-Assisted Age Progression

## Case-intake workflow

Parent/guardian report → `PENDING_POLICE_VERIFICATION` → authorized police or
admin complaint/reference verification → `ACTIVE` → authorized CCTV processing.
The complaint terminology is configurable by workflow; this prototype does not
file an FIR or treat a typed reference number as proof. Every activation and
blocked inactive pipeline attempt is audited.

## Parent-assisted age progression

Child and parent/guardian recent photographs are distinct controlled encrypted
references. Parent images are supporting appearance inputs, not a child identity
or genetic prediction. A generated age-progression candidate is always
`PENDING_REVIEW`; an authorized reviewer must approve it before a separately
provenanced `AGE_PROGRESSED_REFERENCE` embedding can be added.

No trained provider is bundled. The normal provider boundary fails safely if
unconfigured. A development-only placeholder exists for tests, makes no age or
genetic prediction, and still requires reviewer approval.

## Unchanged AI safety rule

Authorized CCTV → YOLO → DeepSORT → InsightFace → attributes → temporal and
explainable evidence → `PENDING` potential match → authorized human
`VERIFY`/`REJECT`. AI never declares a child found, closes a case, or performs
a final review decision.
