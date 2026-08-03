# Public-Web Real-World Notification Set

This directory is a source-audited validation layer, not a real-campus capture set.

- `public_web_candidates.csv` records every official-page candidate considered.
- `manifest.csv` contains the 15 metadata-selected samples.
- `annotations/` contains ground truth transcribed from official page text, independently of model output.
- `source_records/sources.json` preserves source and rights decisions.
- `source_verification.csv` records the latest official-page identity and accessibility check.
- `cache_manifest.csv` records every download attempt plus integrity and duplicate metadata.
- `manual_review_checklist.csv` is the project-owner privacy and Ground Truth checklist.
- `evaluation_set.lock.json` freezes only samples that have passed every preflight gate.
- `.local_cache/` is Git-ignored. Images must never be committed unless an explicit redistribution licence is recorded.

The local preflight cache currently contains 13 of 15 selected images. Codex-assisted visual screening has been recorded for those 13 files without claiming independent human approval: one image has no observed personal detail or QR, while 12 require redaction of public names, portraits, meeting details, and/or QR codes before they can be approved. Two failed downloads remain visually unreviewed. The manifest therefore stays `PAGE_TEXT_VERIFIED_IMAGE_PENDING`, the evaluation lock stays `NOT_READY`, and the formal OCR/Agent run remains `NOT EXECUTED` with no rates reported.

Public availability is not redistribution permission. All selected rows currently use `redistribution_allowed=false` and `local_file_committed=false`.

Run the local preparation audit with:

```powershell
.\.venv\Scripts\python.exe -m glanceflow.evaluation.public_web_preflight --download
```

The command does not run OCR or Agent evaluation. If downloads are blocked or human review remains pending, it truthfully returns `READY_FOR_PUBLIC_WEB_EVALUATION = false`.
