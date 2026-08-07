# Stage 13 real-world validation

## Status

- `REAL_CAMPUS_SAMPLE_COUNT = 0`
- `STATUS = WAITING_FOR_DATA`
- Public repository samples in the Stage 13 manifest: 0
- Local private samples: 0
- Independently approved ground truth: 0
- User-study participants: 0

The project currently has no permitted real-campus capture dataset. Consequently OCR character accuracy, temporal-field accuracy, temporal-role accuracy, evidence completeness, Safety accuracy, wrong execution, false block, and recapture metrics are **NOT_EVALUATED (0 eligible samples)**. This is not a zero score or a successful result.

## What is ready

The repository now contains the Stage 13 manifest schema, source classification, independent ground-truth model, hash and privacy/permission preflight, zero-safe evaluation outputs, failure taxonomy, visual-degradation result schema, OCR-comparison result schema, and a consent-first user-study v2 kit. Existing Stage 8 public-web material remains explicitly `PUBLIC_WEB`; it is not described as campus field collection.

Two CC BY-SA 4.0 Wikimedia Commons posters were identified as future PUBLIC_WEB candidates. Their binaries are not committed because a verified local download, human privacy review, and independent annotation were not completed in this run.

## Frozen-pipeline requirement

The first eligible real-campus batch must be evaluated with the current frozen GlanceFlow OCR, evidence, Safety Gate, Agent, and memory-calendar transaction path before any optimization. A failed sample is assigned to one of: `PERCEPTION_ERROR`, `OCR_ERROR`, `FIELD_EXTRACTION_ERROR`, `TEMPORAL_ROLE_ERROR`, `TEMPORAL_NORMALIZATION_ERROR`, `EVIDENCE_BINDING_ERROR`, `SAFETY_FALSE_BLOCK`, `SAFETY_FALSE_ALLOW`, `AGENT_DECISION_ERROR`, or `TRANSACTION_ERROR`.

## RapidOCR and PaddleOCR

Status: **NOT_EVALUATED**. Comparison is intentionally deferred until eligible real-campus samples exist. RapidOCR remains the production default; PaddleOCR is not promoted or installed on the basis of synthetic or empty results.

## Current limits and next collection step

Recruit 5–8 consenting participants only after the study materials are reviewed. Separately collect 10–20 permitted notices spanning the conditions in the protocol. For each notice: record permission, keep unapproved originals local, sanitize personal data and private QR codes, preserve task-essential title/time/location, strip metadata, compute the final hash, obtain independent annotation and review, then run preflight. No real Google Calendar or Rokid hardware result is claimed.
