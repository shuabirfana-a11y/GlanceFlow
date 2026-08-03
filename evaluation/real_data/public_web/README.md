# Public-Web Real-World Notification Set

This directory is a source-audited validation layer, not a real-campus capture set.

- `public_web_candidates.csv` records every official-page candidate considered.
- `manifest.csv` contains the 15 metadata-selected samples.
- `annotations/` contains ground truth transcribed from official page text, independently of model output.
- `source_records/sources.json` preserves source and rights decisions.
- `source_verification.csv` records the latest official-page identity and accessibility check.
- `cache_manifest.csv` records every download attempt plus integrity and duplicate metadata.
- `sanitized_manifest.csv` links each approved local redaction to its original and records independent integrity metadata.
- `manual_review_checklist.csv` is the project-owner privacy and Ground Truth checklist.
- `evaluation_set.lock.json` freezes only samples that have passed every preflight gate.
- `.local_cache/` contains original downloads and `.sanitized_cache/` contains separately stored redacted copies. Both are Git-ignored. Images must never be committed unless an explicit redistribution licence is recorded.

The original cache contains 13 of 15 selected images. Human reviewer `R01` approved 12 separately stored redacted copies after names, portraits, meeting details, and/or QR codes were irreversibly covered. `PW-011` was not part of that modified-image review. `PW-008` remains a TLS certificate download failure and `PW-013` remains an undecodable-image failure; neither was replaced or marked successful. Reviewer `R01` also approved the Ground Truth for all 9 in-scope, evaluation-eligible samples. The READY lock freezes exactly those 9 samples; the other 6 selected samples remain excluded with their complete failure or out-of-scope records intact.

Formal PUBLIC_WEB OCR/Agent results are written under `outputs/evaluation/public_web/`. They are validation results for public-web notification images only, not evidence from a real-campus capture set or a human-user experiment.

Public availability is not redistribution permission. All selected rows currently use `redistribution_allowed=false` and `local_file_committed=false`.

Run the local preparation audit without downloading again:

```powershell
.\.venv\Scripts\python.exe -m glanceflow.evaluation.public_web_preflight
```

The command verifies original and sanitized integrity but does not itself run OCR or Agent evaluation. If any required review for an otherwise eligible sample remains pending, it truthfully returns `READY_FOR_PUBLIC_WEB_EVALUATION = false`; otherwise it generates a hash-bound READY lock for formal evaluation.
