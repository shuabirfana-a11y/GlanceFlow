# Stage 8 Public-Web Data Audit

## Outcome

The project now has a third, explicitly separate evidence layer: **Public-Web Real-World Notification Set (`PUBLIC_WEB`)**. It is neither the synthetic benchmark nor a real-campus capture set.

## Source audit

- 31 official university or university-unit pages were reviewed.
- 15 records were metadata-selected for variety: ordinary events, online events, dense schedules, multi-day notices, deadlines, and source-page/date ambiguity.
- Ground truth was transcribed independently from official page text and reviewed under anonymous annotator/reviewer IDs.
- Rejection reasons are retained, including insufficient fields, unstable image URLs, privacy risk, multi-notice ambiguity, and restrictive reuse language.

## Rights and privacy

No selected source exposed an explicit image redistribution licence. Therefore:

- all selected rows use `redistribution_allowed=false`;
- all selected rows use `local_file_committed=false`;
- zero source images are committed to Git;
- any future download goes only to the Git-ignored `.local_cache/` directory;
- visual privacy review is required before any image enters formal evaluation.

The Westlake and SUFE samples are specifically flagged for possible email/QR/contact content. The SWJTU source explicitly restricts unauthorized reuse. None of those images is redistributed by this repository.

## Execution status

**NOT EXECUTED — LOCAL IMAGE CACHE / VISUAL PRIVACY REVIEW PENDING**

The repository contains 15 page-text annotations, but it does not contain the image bytes. Metadata review is not treated as OCR evidence. Consequently:

- formal Public-Web samples evaluated: 0;
- OCR and Agent metrics: not calculated;
- six-classification counts: not calculated;
- Synthetic-vs-Public-Web differences: not calculated;
- statistical significance: not claimed;
- real-campus generalization: not claimed.

This is an intentional evidence boundary, not a zero score.

## Other Stage 8 work

Real campus capture remains `NOT EXECUTED` (0 samples). The真人 user study remains `NOT EXECUTED` (0 participants). Stage 9 has not started, and the Agent core was not modified.
