# Public-Web Real-World Notification Set

This directory is a source-audited validation layer, not a real-campus capture set.

- `public_web_candidates.csv` records every official-page candidate considered.
- `manifest.csv` contains the 15 metadata-selected samples.
- `annotations/` contains ground truth transcribed from official page text, independently of model output.
- `source_records/sources.json` preserves source and rights decisions.
- `.local_cache/` is Git-ignored. Images must never be committed unless an explicit redistribution licence is recorded.

The current records use `PAGE_TEXT_VERIFIED_IMAGE_PENDING`: page text and metadata have been reviewed, but the image bytes are not in the local cache and have not completed visual privacy review. Therefore the formal OCR/Agent run remains `NOT EXECUTED` and no rates are reported.

Public availability is not redistribution permission. All selected rows currently use `redistribution_allowed=false` and `local_file_committed=false`.
