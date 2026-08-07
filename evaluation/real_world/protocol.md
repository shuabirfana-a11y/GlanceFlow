# Collection and annotation protocol

## Scope

Collect 10–20 permitted campus notices for the first batch, then ideally expand to 30–50. Cover clear, perspective, distant, occluded, glare, low-light, complex-background, multi-column, QR-interfered, multi-date/time, deadline, cancellation, reschedule, weekday-conflict, relative-time, privacy-bearing, multi-event, and non-executable notices.

## Permission and privacy gate

Record every manifest field before evaluation. Without explicit permission, a sample is `REAL_CAMPUS_LOCAL`, stays under ignored storage, and cannot be used in public output. Remove or blur names, phone numbers, student IDs, email addresses, faces, and private QR codes; preserve only the title, time, and location needed for the task. Strip metadata and verify the final file manually.

## Independent ground truth

One annotator records title, event start/end, location, registration/submission deadlines, check-in/publish times, cancellation/reschedule state, temporal roles, ambiguity, executability, OCR line, bounding box, and source frame. A second person reviews it. Predictions never populate or rewrite ground truth.

## Frozen first run

Run the current GlanceFlow version before OCR or Agent changes. Side-effect tests use only `MemoryCalendar`; never use a personal calendar. Record OCR, fields, temporal roles, evidence, Safety decision, Agent action, recapture/clarification, and any wrong execution.

## Visual conditions

For a permitted source, evaluate `CLEAR`, `PERSPECTIVE`, `BLUR`, `LOW_LIGHT`, `GLARE`, `OCCLUDED`, and `DISTANT`. Generated degradations must be labeled as transformations of one source, not new real captures. Low-quality inputs should prefer recapture over unsafe execution.

## Metrics

Every metric reports numerator, denominator, contributing sample IDs, and value. With no eligible sample, the value is `NOT_EVALUATED`, never zero performance. Failures use the fixed Stage 13 taxonomy in the evaluator.
