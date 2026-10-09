# SeaweedFS Console

## Description

[SeaweedFS](https://github.com/seaweedfs/seaweedfs) ships two browser interfaces: the filer console for browsing stored files and the master console for cluster state.
This role serves both behind an administrator-only oauth2-proxy.

## Overview

The object store itself lives in [web-svc-seaweedfs](../web-svc-seaweedfs/), which owns the storage engine, the per-consumer identities and the public S3 endpoint.
This role adds only the human-facing half: an nginx sidecar that routes two canonical domains to the engine's internal filer and master ports.

- `filer.seaweedfs.s3.*` serves the filer web UI.
- `master.seaweedfs.s3.*` serves the master web UI.

The sidecar reaches the engine over the shared object-store network, so the console can be deployed, removed or left out of a node without touching the store.
A node that does not run this role keeps its object store and its S3 endpoint; it simply has no browser console.

Per-consumer S3 identities are rendered into `s3.json`: each consuming role receives an access key and bucket-scoped `Read`, `Write`, `List`, and `Tagging` actions, and consumers marked `public` additionally receive anonymous read on their bucket.
Consumer buckets are created through `weed shell` when a consumer role requests provisioning.

In embedded mode (`shared: false`) a consumer's compose stack receives a storage-only SeaweedFS container without UI or published ports.
The embedded S3 listener performs no authentication, so it MUST stay confined to the consumer's isolated compose network.

## Features

- **Admin-gated consoles:** Both interfaces are reachable only for members of the administrator group.
- **Separable from the store:** The console deploys and scales independently of the storage engine.
- **Onion-capable:** Unlike the storage engine, the console is a browser surface and is served over the node onion when Tor is enabled.

## Further Resources

- [SeaweedFS on GitHub](https://github.com/seaweedfs/seaweedfs)
- [SeaweedFS Wiki](https://github.com/seaweedfs/seaweedfs/wiki)
- [Corporate design review: screenshots in light, dark, desktop and mobile](https://claude.ai/artifact/KARCkLWPrQKjbZDUynYfit)
