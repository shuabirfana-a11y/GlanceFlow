# GlanceFlow Agent Rules

- Development and verification run on Windows.
- Prefer `C:\x\python.exe`; after setup use `.venv\Scripts\python.exe`.
- Do not use Linux-only commands or shell syntax.
- Do not fabricate source data, test results, or execution results.
- Run relevant tests after every code change and the full suite before handoff.
- A language model may propose a draft but may never bypass the action safety gate.
- An unverified draft must never trigger an external operation.
- Do not expand Stage 1 beyond data structures, the safety gate, CLI, examples, and tests.

