# GlanceFlow Agent Rules

- Development and verification run on Windows.
- Prefer `C:\x\python.exe`; after setup use `.venv\Scripts\python.exe`.
- Do not use Linux-only commands or shell syntax.
- Do not fabricate source data, test results, or execution results.
- Run relevant tests after every code change and the full suite before handoff.
- A language model may propose a draft but may never bypass the action safety gate.
- An unverified draft must never trigger an external operation.
- Current scope includes Stage 1 safety, Stage 2 local OCR, Stage 3 provider-neutral calendar transactions, and the Stage 4 local first-person glasses interaction simulator.
- Real Google calls require an explicitly configured non-primary test calendar and local untracked credentials; never log credentials or tokens.
- Stage 4 video, voice, motion and HUD components remain local simulator ports; do not claim real glasses deployment.
- Do not add continuous recording, databases, maps, automatic registration, recommendations, Gmail, Google Tasks, real wearable SDKs, or multi-agent behavior.
- Moving or unknown posture may prepare a draft but must never confirm, create, or undo calendar events.
- Temporary uploaded video is deleted by default; retain only the automatically selected evidence frame until the session is cleared.
