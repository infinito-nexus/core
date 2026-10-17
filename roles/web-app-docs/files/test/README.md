# Instruction replay

The CLI test of `web-app-docs` reads the Production block out of the running documentation site and executes it, so the published instructions are proven rather than reviewed.

## Cast

| | What it is | What runs there |
| --- | --- | --- |
| 🖥️ **Stack host** | the worker the outer play already runs on | `test.sh`, `machine.sh`, and a block that starts a container |
| 🎯 **Target** | a throwaway container, project `docs-guide-<role>` | systemd and an ssh server, nothing else until the deploy lands; a host install also runs there |
| 🐳 **Recipe container** | started by the block's own `docker run`, on the stack daemon | the deploy that the instructions tell a reader to run |

The target is what the instructions call "a managed server". It is deliberately bare: everything else it ends up with arrives through the deploy under test.

A role that ships no container stack publishes a host install instead of a recipe: a block that opens with `git clone` and configures the machine it runs on. The target is that machine, so the block is replayed inside it over the checkout mounted at `DOCS_TEST_SRC_DIR`, and the two clone lines are dropped so the replay reads the tree under test. A block that neither starts a container nor clones the repository fails the test.

## Schema

```mermaid
flowchart TD
    subgraph HOST["🖥️ stack host"]
        direction TB
        TEST["1️⃣ 🧪 test.sh<br>returns early unless DOCS_TEST_MODE=compose"]
        EXTRACT["2️⃣ 📖 extract.py<br>reads the block off the live docs site"]
        FILL["3️⃣ 🔑 ed25519 pair + placeholder fill<br>everything except HOST"]
        MACHINE["4️⃣ 🚜 machine.sh"]
        SHAPE{"🔀 docker run or git clone"}
        ADDR["7️⃣ 📍 HOST = the target's bridge address"]
        GUARD["8️⃣ 🚦 placeholder guard"]
        BLOCK["9️⃣ ▶️ bash -e block.sh"]
    end

    subgraph TARGET["🎯 target container"]
        direction TB
        INIT["5️⃣ ⚙️ systemd, no engine<br>Dockerfile + init.sh"]
        SSHD["6️⃣ 🔐 sshd.sh<br>ssh server + run key for root"]
        HOSTRUN["▶️ bash -e block.sh in the mounted checkout<br>clone lines dropped"]
        DEPLOYED["🔟 📦 docker-ce and the role"]
    end

    RECIPE["🐳 docker run &lt;deploy image&gt;<br>on the stack daemon"]

    TEST --> EXTRACT --> FILL --> MACHINE
    MACHINE -->|"🌉 compose up"| INIT
    INIT -->|"⏳ await systemd"| SHAPE
    SHAPE -->|"🐳 recipe"| SSHD
    SHAPE -->|"🏠 host install"| HOSTRUN
    SSHD --> ADDR --> GUARD --> BLOCK
    BLOCK --> RECIPE
    RECIPE -->|"🔗 ssh as root"| DEPLOYED
    HOSTRUN --> DEPLOYED
    MACHINE -.->|"🧹 trap EXIT"| TARGET

    classDef host fill:#e8f0fe,stroke:#1a73e8,color:#102a43;
    classDef target fill:#e6f4ea,stroke:#137333,color:#0b2e13;
    classDef pivot fill:#fef7e0,stroke:#b06000,color:#3d2600;
    classDef recipe fill:#f3e8fd,stroke:#8430ce,color:#2a0b45;
    class TEST,EXTRACT,FILL,MACHINE,BLOCK host;
    class INIT,SSHD,HOSTRUN,DEPLOYED target;
    class SHAPE,ADDR,GUARD pivot;
    class RECIPE recipe;
```

🔵 stack host · 🟢 target · 🟣 the recipe's own container · 🟠 the steps that bridge them

## Flow

| # | Step | Detail |
| --- | --- | --- |
| 1️⃣ | 🧪 `test.sh` starts on the stack host | returns early unless the deployment mode is compose |
| 2️⃣ | 📖 `extract.py` writes `block.sh` | fetches the role's page over `DOCS_TEST_BASE_URL`; an empty block fails the test, and `bash -n` parses it before anything runs it |
| 3️⃣ | 🔑 key pair and placeholders | an ed25519 pair per run under `DOCS_TEST_WORK`; every placeholder except `HOST` is substituted |
| 4️⃣ | 🚜 `machine.sh` brings the target up | from `compose.yml`, on the default bridge |
| 5️⃣ | ⚙️ the target boots | image built from `Dockerfile` + `init.sh`; `MACHINE_BASE_IMAGE` comes from `INFINITO_PARENT_IMAGE` in the checkout's `.env` |
| 🔀 | the shape decides where the block runs | `docker run` on the stack host, `git clone` inside the target; steps 6️⃣ to 9️⃣ are the first of the two |
| 6️⃣ | 🔐 `sshd.sh` is piped in | installs an ssh server, authorizes the run's public key for `root`, writes a `PermitRootLogin prohibit-password` drop-in |
| 7️⃣ | 📍 `HOST` is filled | `container inspect --type container` reads the bridge address; the bridge has no DNS, so it is an address and not a name |
| 8️⃣ | 🚦 the guard runs | fails on any remaining `<your-`; it runs **after** step 7, because the address does not exist before it |
| 9️⃣ | ▶️ the block executes on the stack host | its `docker run` starts the published deploy image on the stack daemon |
| 🔟 | 📦 the deploy reaches the target over ssh as `root` | the target receives `docker-ce` and the role; its `/var/lib/docker` is a named volume, so the installed daemon writes to a real filesystem |
| 🧹 | teardown | `compose down -v --rmi local` from an `EXIT` trap |

## Environment

| Variable | Source | Use |
| --- | --- | --- |
| `DOCS_TEST_BASE_URL` | `templates/test.env.j2` | documentation site the block is read from |
| `DOCS_TEST_ROLE` | `templates/test.env.j2` | role whose page carries the instructions; names the compose project |
| `DOCS_TEST_MODE` | `templates/test.env.j2` | deployment mode; the test runs only for compose |
| `DOCS_TEST_DOMAIN` | `templates/test.env.j2` | fills `<your-domain>` |
| `DOCS_TEST_DNS` | `templates/test.env.j2` | fills `<your-clearnet-resolver>` |
| `DOCS_TEST_SRC_DIR` | `templates/test.env.j2` | checkout holding the generated `.env`; mounted into the target at the same path, where a host install replays from it |
| `DOCS_TEST_TIMEOUT` | `templates/test.env.j2` | wait for the on-demand documentation build |
| `DOCS_TEST_WORK` | `test.sh` | holds the replay key pair |
| `DOCS_TEST_REPLAY_PUBKEY` | `test.sh` | public half, consumed by `sshd.sh` |

## Files

| File | Role |
| --- | --- |
| `test.sh` | entry point; extraction, key pair, placeholder fill |
| `extract.py` | pulls the Production block off the live documentation site |
| `machine.sh` | target lifecycle, `HOST` fill, guard, replay, teardown |
| `compose.yml` | the target service, on the default bridge, with a named volume at `/var/lib/docker` |
| `Dockerfile` | builds the target from the distribution base image |
| `init.sh` | installs systemd into that image, and deliberately no container engine |
| `sshd.sh` | ssh server and the run's authorized key, piped into the running target |
