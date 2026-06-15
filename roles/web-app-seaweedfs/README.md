# SeaweedFS

## Description

[SeaweedFS](https://github.com/seaweedfs/seaweedfs) is a fast distributed storage system for blobs, objects, and files.
It exposes an S3-compatible API, so applications store and retrieve objects with standard S3 SDKs and CLIs.

## Overview

This role deploys SeaweedFS as the central provider of the project-wide object-store service (engine `seaweedfs`).
Web-app roles consume it like a database: they enable a `seaweedfs` service in their `meta/services.yml` and resolve host, port, bucket, and credentials through the `objstore` lookup.
A single server container runs master, volume, filer, and the S3 gateway in one process, accompanied by an nginx sidecar that routes the admin UIs.
The role serves three canonical domains:

- `api.seaweedfs.s3.*` is the public S3 endpoint and is reachable without SSO gating.
- `filer.seaweedfs.s3.*` serves the filer web UI behind an admin-only oauth2-proxy.
- `master.seaweedfs.s3.*` serves the master web UI behind the same admin-only oauth2-proxy.

Per-consumer S3 identities are rendered into `s3.json`: each consuming role receives an access key and bucket-scoped `Read`, `Write`, `List`, and `Tagging` actions, and consumers marked `public` additionally receive anonymous read on their bucket.
Consumer buckets are created through `weed shell` when a consumer role requests provisioning.

In embedded mode (`shared: false`) a consumer's compose stack receives a storage-only SeaweedFS container without UI or published ports.
The embedded S3 listener performs no authentication, so it MUST stay confined to the consumer's isolated compose network.

## Features

- **S3-compatible API:** Standard S3 SDKs and CLIs work against the gateway for uploads, media, attachments, and exports.
- **Central object-store service:** One shared instance serves all consuming web-app roles, mirroring the shared database pattern.
- **Per-consumer isolation:** Every consumer receives its own identity and bucket with bucket-scoped actions only.
- **Admin-gated UIs:** The filer and master web interfaces are reachable only for members of the administrator group via oauth2-proxy.
- **Embedded mode:** Roles that opt out of the shared instance run a private storage-only container inside their own compose network.

## Further Resources

- [SeaweedFS on GitHub](https://github.com/seaweedfs/seaweedfs)
- [SeaweedFS Wiki](https://github.com/seaweedfs/seaweedfs/wiki)
- [Amazon S3 API](https://aws.amazon.com/s3/)

## Credits

Developed and maintained by **Kevin Veen-Birkenbach**.
Learn more at [veen.world](https://www.veen.world).
Part of the [Infinito.Nexus Project](https://s.infinito.nexus/code).
Licensed under the [Infinito.Nexus Community License (Non-Commercial)](https://s.infinito.nexus/license).
