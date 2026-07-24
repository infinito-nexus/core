# apt readiness tasks

Included by [tasks/stages/01_constructor.yml](../../stages/01_constructor.yml)
before the first apt task of a play.

- [ready.yml](./ready.yml) is the entry point: it gates the neutralize
  include on `DOCKER_IN_CONTAINER` and always waits for the dpkg lock.
- [neutralize.yml](./neutralize.yml) stops and masks the apt-daily units,
  gated on a running systemd (`/run/systemd/system`, the sd_booted
  convention).

```mermaid
flowchart TB
    stage01["01_constructor.yml"]
    ready["ready.yml"]
    incontainer{"DOCKER_IN_CONTAINER?"}
    neutralize["neutralize.yml"]
    sdbooted{"/run/systemd/system exists?"}
    stopmask["stop and mask the apt-daily timers and services"]
    wait["wait for the dpkg lock"]

    stage01 --> ready
    ready --> incontainer
    incontainer -->|"true"| neutralize
    incontainer -->|"false"| wait
    neutralize --> sdbooted
    sdbooted -->|"true"| stopmask
    sdbooted -->|"false"| wait
    stopmask --> wait
```
