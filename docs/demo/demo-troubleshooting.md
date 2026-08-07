# Demo troubleshooting

- Healthcheck fails: run `.\.venv\Scripts\python.exe -m glanceflow.demo.healthcheck` and address the named component.
- Port 8765 occupied: close the unrelated local process or start the app manually on another port.
- Browser does not open: visit `http://127.0.0.1:8765/?scenario=GF-DEMO-01`.
- OCR first run is slow: allow model initialization; displayed latency is measured and labeled local Windows simulation.
- Stale session: run `scripts/reset_competition_demo.ps1`, then relaunch.
- No network: expected; the competition path has no network dependency.
- Rokid unavailable: expected; this stage is not tested on physical Rokid hardware.
