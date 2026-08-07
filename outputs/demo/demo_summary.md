# Competition demo summary

- Environment: **LOCAL WINDOWS SIMULATION**
- Network required: **no**
- Calendar: **MemoryCalendar only**
- Rokid hardware validation: **not performed**

## Scenario outcomes

| Scenario | Safety status | Action | Transaction | Calendar events |
|---|---|---|---|---:|
| GF-DEMO-01 | READY_TO_CONFIRM | EXECUTION_COMPLETE | VERIFIED | 1 |
| GF-DEMO-02 | READY_TO_CONFIRM | EXECUTION_COMPLETE | VERIFIED | 2 |
| GF-DEMO-03 | RECAPTURE_REQUIRED | RECAPTURE | NOT_STARTED | 0 |
| GF-DEMO-04 | CONTRADICTION_BLOCKED | BLOCK | NOT_STARTED | 0 |
| GF-DEMO-05 | READY_TO_CONFIRM | EXECUTION_COMPLETE | VERIFIED | 2 |
| GF-DEMO-06 | READY_TO_CONFIRM | EXECUTION_COMPLETE | UNDONE | 0 |
| GF-DEMO-07 | READY_TO_CONFIRM | BLOCK_DUPLICATE | VERIFIED | 1 |
| GF-DEMO-08 | READY_TO_CONFIRM | RECOVERY_COMPLETE | ROLLED_BACK | 0 |

## Repeatability

Six core simulator scenarios were each run 10 times. These are deterministic simulator repeatability checks, not real-user or hardware reliability statistics.
