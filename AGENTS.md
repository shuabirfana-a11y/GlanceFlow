# GlanceFlow Agent Rules

- Development and verification run on Windows.
- Prefer `C:\x\python.exe`; after setup use `.venv\Scripts\python.exe`.
- Do not use Linux-only commands or shell syntax.
- Do not fabricate source data, test results, or execution results.
- Run relevant tests after every code change and the full suite before handoff.
- A language model may propose a draft but may never bypass the action safety gate.
- An unverified draft must never trigger an external operation.
- Current scope includes Stage 1 data structures/safety gate and Stage 2 local OCR, image quality, deterministic extraction, synthetic fixtures, CLI, and tests.
- Do not add calendars, OAuth, external execution, video, voice, HUD, web UI, databases, maps, automatic registration, or multi-agent behavior in Stage 2.
