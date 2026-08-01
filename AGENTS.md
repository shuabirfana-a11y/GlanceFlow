# GlanceFlow Agent Rules

- Development and verification run on Windows.
- Prefer `C:\x\python.exe`; after setup use `.venv\Scripts\python.exe`.
- Do not use Linux-only commands or shell syntax.
- Do not fabricate source data, test results, or execution results.
- Run relevant tests after every code change and the full suite before handoff.
- A language model may propose a draft but may never bypass the action safety gate.
- An unverified draft must never trigger an external operation.
- Current scope includes Stage 1 safety, Stage 2 local OCR, and Stage 3 provider-neutral calendar transactions with a memory provider and Google contract adapter.
- Real Google calls require an explicitly configured non-primary test calendar and local untracked credentials; never log credentials or tokens.
- Do not add video, voice, HUD, web UI, databases, maps, automatic registration, recommendations, Gmail, Google Tasks, or multi-agent behavior in Stage 3.
