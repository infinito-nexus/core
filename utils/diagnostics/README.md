# Diagnostics: recursive container rescue snapshot

`container.py` is the single failure-diagnostics entry point. The CI
workflows (compose + swarm) call it once on the runner when a job fails;
it captures the current level and then recurses itself through every
Docker-in-Docker boundary, so one call collects evidence from the
outermost runner down to the innermost application container. It always
exits 1.

```mermaid
flowchart TB
    subgraph entry["🩺 One workflow call on failure()"]
        wf["⚙️ CI step (compose + swarm identical)<br/>INFINITO_RESCUE_DIAGNOSTICS_DIR=/tmp/rescue-diagnostics/&lt;app&gt;<br/>python3 utils/diagnostics/container.py &lt;app&gt; &lt;context&gt;"]:::infra
    end

    subgraph level["📸 Per-level capture (repeated on every depth)"]
        direction TB
        host["🖥️ Host facts<br/>meta, uname, df/free/uptime,<br/>journal, dmesg OOM evidence"]:::store
        dumps["📂 local-dumps/<br/>in-play role evidence from<br/>DIR_RESCUE_DIAGNOSTICS (pg_hba, xwiki)"]:::store
        rtc["🐳 Runtime state<br/>info, stats, ps -a,<br/>per-container logs + inspect"]:::store
        svc["🐝 Swarm services<br/>ls, per-service ps + logs"]:::store
    end

    subgraph recursion["🔁 Recursion (RESCUE_MAX_DEPTH, default 3)"]
        direction TB
        probe["🔍 For every RUNNING container:<br/>has python3 + docker/container runtime?"]:::step
        copy["📤 Copy itself in<br/>(stdin → /tmp/rescue-self.py)"]:::step
        nested["🩺 Run nested capture<br/>RESCUE_DEPTH+1, own staging dir"]:::step
        pull["📥 tar the nested snapshot back to<br/>containers/&lt;name&gt;/nested/ + clean up"]:::step
        probe -->|yes| copy --> nested --> pull
        probe -.->|no: plain app container,<br/>logs already captured| skipped["⏭️ skip"]:::skip
    end

    wf --> level --> recursion
    nested -.->|same program,<br/>one level deeper| level

    result["🗂️ Artifact tree (uploaded by CI)<br/>&lt;app&gt;-&lt;stamp&gt;-&lt;pid&gt;/<br/>├── meta/system/journal/…<br/>├── local-dumps/…<br/>├── containers/&lt;name&gt;.log + .inspect.json<br/>├── containers/&lt;did-node&gt;/nested/&lt;app&gt;-…/ (recursion)<br/>└── services/&lt;svc&gt;.log + .ps.txt"]:::store
    recursion --> result

    classDef infra fill:#f3f7fb,stroke:#d6e2ee,color:#455a64;
    classDef store fill:#f1f8f6,stroke:#d5e7e2,color:#455a64;
    classDef step fill:#fbf6f0,stroke:#eee1cf,color:#455a64;
    classDef skip fill:#f7f8f9,stroke:#e3e6e9,color:#455a64;
    style entry fill:#ffffff,stroke:#e6e6e6;
    style level fill:#ffffff,stroke:#e6e6e6;
    style recursion fill:#ffffff,stroke:#e6e6e6;
```

Ansible `rescue:` blocks are forbidden
(`tests/lint/ansible/structure/test_no_rescue_blocks.py`); the rare
justified block (`# nocheck: rescue-<reason>`) leaves its role-specific
evidence in `DIR_RESCUE_DIAGNOSTICS`, which every capture level ships as
`local-dumps/`.
