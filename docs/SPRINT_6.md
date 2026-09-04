# Sprint 6 — Authorized Notifications and Multi-Station Communication

Sprint 6 adds a local, database-backed notification layer after the existing AI and human-review workflow. It does not alter YOLO, DeepSORT, InsightFace, scoring thresholds, or the rule that every AI result starts as `PENDING`.

## Lifecycle

```text
AI PENDING match → SQLite potential match → authorized in-app notifications
                                      → authorized human VERIFY / REJECT
                                      → conservative follow-up notifications
```

`services/notification_service.py` owns templates, recipient selection, deduplication, and delivery. Its default `DatabaseNotificationProvider` changes the local row from `PENDING` to `SENT`; it does not contact SMS, email, WhatsApp, or a real external service. Future providers can implement the small `NotificationProvider` interface and must remain explicitly configured.

The `notifications` table records recipient, role, type, channel, status, timestamps, failure reason, and bounded safe metadata. It has a uniqueness rule for case + potential match + recipient + notification type, so retries cannot create an unlimited stream of the same alert. Creation, send, failure, and read events are audited as `SYSTEM` where no human actor performed the action.

## Information boundaries

Parents receive only conservative, case-owned status wording: a potential match is under authorized review; no score, CCTV source, evidence, station, raw path, reviewer identity, or claim that a child was found is included. Police and reviewers assigned to the original or explicitly active station receive controlled internal detail, including an evidence *ID* rather than a filesystem path. Administrators can inspect system notification history through the existing audit role.

## Multi-station and location foundation

`get_authorized_case_stations(case_id)` returns only the case’s original station plus active records in `case_station_assignments`. Those are the only staff recipients. The case page lets ADMIN/POLICE create, update, or close an assignment; every change is audited. Parents cannot manage assignments.

`match_observations` connects a match to an existing, active registered camera and timestamp. The newest observation can be used in an internal notification as **Last observed camera**. It is an authorized CCTV observation, not live GPS, does not invent coordinates, and is never shown in parent notifications.

## Run and test

Run `python -m unittest discover -s tests -v`. The tests use temporary SQLite databases and the local provider only. To start the dashboard, configure the bootstrap administrator described in `RUN_GUIDE.md`, then run `streamlit run app.py`.

## Prototype limitations and next work

This is in-app delivery only. Production needs separately approved email/SMS/push providers, encrypted transport/storage, MFA, server-side sessions, delivery receipts, formal retention/legal-hold policy, deployment hardening, and governance review. It does not provide a mobile app, live multi-camera infrastructure, GPS tracking, emergency dispatch, or automatic recovery decisions.
