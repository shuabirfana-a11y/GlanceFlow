# Stage 13 real-world validation

This directory keeps ground truth separate from predictions and distinguishes `SYNTHETIC`, `PUBLIC_WEB`, `REAL_CAMPUS_LOCAL`, and `REAL_CAMPUS_PUBLIC` sources.

Current state: `REAL_CAMPUS_SAMPLE_COUNT=0`, `STATUS=WAITING_FOR_DATA`. No online image is described as an on-site campus capture. `raw/` and `private/` are ignored. Only an image with verified reuse permission, completed sanitization, independent annotation, and a matching hash may be marked `allowed_for_repository=true`.

Run preflight with:

```powershell
.\.venv\Scripts\python.exe -m glanceflow.evaluation.real_world_preflight
```

Run the zero-safe evaluation pipeline with:

```powershell
.\.venv\Scripts\python.exe -m glanceflow.evaluation.real_world
```

The existing Stage 8 `evaluation/real_data/public_web/` dataset remains a separate PUBLIC_WEB source and is not counted as real-campus data.
