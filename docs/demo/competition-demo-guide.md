# Competition demo guide

Run `powershell -ExecutionPolicy Bypass -File scripts/run_competition_demo.ps1`. The launcher checks the local environment, runs the demo healthcheck, starts the service, waits for health, and opens `GF-DEMO-01`.

The demo is entirely offline: RapidOCR, deterministic extraction/temporal processing, the production Safety Gate, Action Preflight, trusted transaction manager, MemoryCalendar, and Fake/Local device boundaries. It does not use Google APIs, network LLMs, cloud OCR, Rokid services, or a personal calendar.

The interface separates first-person evidence, user-facing HUD, public Agent decision, field evidence, compact Safety states, transactions, and measured local timings. IDs and hashes are shortened for display. Technical details contain no chain-of-thought, credentials, account names, or absolute paths.

Use `scripts/reset_competition_demo.ps1` between presentations. This removes only known temporary demo paths; code, tests, and tracked outputs are preserved.
