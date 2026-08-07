# Demo scenarios

| ID | Scenario | Expected visible behavior |
|---|---|---|
| GF-DEMO-01 | Normal event | Evidence-bound confirmation, create, readback, verify |
| GF-DEMO-02 | Event + deadline | Separate event and registration deadline; atomic two-event transaction |
| GF-DEMO-03 | Low resolution | `RECAPTURE_REQUIRED`; zero calendar events |
| GF-DEMO-04 | Date-weekday contradiction | Temporal contradiction blocked; zero events |
| GF-DEMO-05 | Calendar conflict | Ordinary confirmation rejected; explicit conflict acceptance required |
| GF-DEMO-06 | Undo | Verified transaction undone by recorded transaction/event IDs |
| GF-DEMO-07 | Duplicate | Second preflight blocks; no duplicate event |
| GF-DEMO-08 | Readback mismatch | Create, mismatch, rollback, verified absence |

Every outcome is produced by existing GlanceFlow pipeline and transaction components. Scenario files select inputs, user commands, and isolated fault plans; they do not provide final Safety or transaction states.
