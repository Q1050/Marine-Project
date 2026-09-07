# Buildathon architecture

```mermaid
flowchart LR
    A[Public or partner sighting] --> B[Observation + media provenance]
    B --> C[AI-supported identification]
    C --> D[Jurisdiction review queue]
    D --> E[Expert verification]
    E --> F[Governed occurrence-evidence review]
    F --> G[Jurisdiction public directories]
    F --> H[Monitoring and descriptive context]
    I[WoRMS taxonomy source] --> J[Regional candidate manifest]
    J --> K[Human taxonomy review]
    K --> L[Governed regional registry]
    M[Environmental datasets] --> N[Versioned suitability deployment]
    N --> H
    H --> O[Human-reviewed early warning]
```

The arrows describe controlled handoffs, not automatic scientific promotion. Authentication and jurisdiction grants constrain private operational evidence. Platform-admin workflows govern sources and scientific state. Public endpoints expose only approved projections and safe attribution.

