# Device fallback strategy

Fallback is explicit and produces `DEVICE_FALLBACK {from_adapter, to_adapter,
reason, occurred_at}` for the public decision/audit trace.

- Camera: configured device → local camera implementation when explicitly
  selected → file upload. Stage 12 implements the safe file-upload fallback; it
  does not open a Windows webcam without user action.
- Voice: device voice text → local microphone implementation when configured →
  local text command. Stage 12 implements text command.
- HUD: glasses HUD → browser HUD.

No fallback confirms an action, changes Safety Gate results, or retries a
Calendar write. If no compatible capability exists, the operation fails
explicitly.
