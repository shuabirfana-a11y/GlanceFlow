# GlanceFlow final architecture

```mermaid
flowchart TD
    A["First-Person Input"] --> B["Device Adapter"]
    B --> C["Perception"]
    C --> D["Evidence Binding"]
    D --> E["Temporal Semantics"]
    E --> F["Risk-Aware Agent"]
    F --> G["Safety Gate"]
    G --> H["Action Preflight"]
    H --> I["User Confirmation"]
    I --> J["Trusted Transaction"]
    J --> K["Readback / Recovery"]
    F -. "public state, rules and reason" .-> T["Decision Trace"]
```

The main chain is deliberately compact. Device adapters provide transport and capability boundaries, but never make temporal, Safety or Calendar decisions. The Decision Trace is a separate public audit artifact; it contains structured rules and reasons, not hidden chain-of-thought.

An export-ready vector is available at `docs/competition/final-architecture.svg`.
