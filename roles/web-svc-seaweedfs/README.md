# SeaweedFS

## Description

[SeaweedFS](https://github.com/seaweedfs/seaweedfs) is a fast distributed storage system for blobs, objects, and files.
It exposes an S3-compatible API, so applications store and retrieve objects with standard S3 SDKs and CLIs.

## Overview

This role deploys SeaweedFS as the central provider of the project-wide object-store service (engine `seaweedfs`).
Web-app roles consume it like a database: they enable a `seaweedfs` service in their `meta/services.yml` and resolve host, port, bucket, and credentials through the `objstore` lookup.
A single server container runs master, volume, filer, and the S3 gateway in one process.
The role serves one canonical domain:

- `api.seaweedfs.s3.*` is the public S3 endpoint and is reachable without SSO gating.

The browser interfaces for the filer and master are served by [web-app-seaweedfs](../web-app-seaweedfs/), which reaches this role over the shared object-store network.
A node running this role without the console keeps its object store and its S3 endpoint; it simply has no browser console.

Per-consumer S3 identities are rendered into `s3.json`: each consuming role receives an access key and bucket-scoped `Read`, `Write`, `WriteAcp`, `List`, and `Tagging` actions, and consumers marked `public` additionally receive anonymous read on their bucket.
Consumer buckets are created through `weed shell` when a consumer role requests provisioning.
The bucket of every consumer not marked `public` carries a bucket policy statement `DenyAnonymousRead` that denies all unsigned reads, so a `public-read` ACL set by an app never exposes an object; signed and presigned requests are unaffected.
Every deploy of this role converges that statement on all existing consumer buckets, adding it to private buckets and removing it from public ones, and a consumer's provisioning applies it right after creating the bucket.
Other statements an operator adds to a consumer's bucket policy are kept.
While `web-app-semaphore` enables its `export-runner`, the role also renders the identity `export` with `Read`, `Write` and `List` on the platform bucket `exports`, creates that bucket and keeps `DenyAnonymousRead` on it; the identity's keys come from the Semaphore role's secrets, and the deploy fails while they are empty.

Every vhost of a shared consumer marked `public` also serves its bucket under `/_infinito/objstore/<bucket>/`, and `lookup('objstore', application_id, 'relative_url')` returns that host-relative base for URLs a browser loads.
The route passes `GET` and `HEAD` for object keys only: it answers `404` for a path ending in `/`, drops the query string and the `Authorization` and `Cookie` headers, and sends the request over the loopback to the `api.seaweedfs.s3.*` vhost.
Responses carry `X-Content-Type-Options: nosniff` and a `sandbox` Content Security Policy.
A consumer without `public: true` or in embedded mode gets an empty `relative_url` and no route.

In embedded mode (`shared: false`) a consumer's compose stack receives a storage-only SeaweedFS container without UI or published ports.
The embedded S3 listener starts without identities and accepts unauthenticated requests until the background `s3.configure` grant at startup registers the consumer identity; from then on it authenticates against that identity.
Embedded buckets carry no `DenyAnonymousRead` statement because the listener publishes no port, so the container MUST stay confined to the consumer's isolated compose network.

## Workspace buckets

Each workspace of the store keeps its OpenTofu state in a bucket of its own.
`workspace apply` runs `tasks/workspace.yml` with `WORKSPACE`, a lowercase UUID, and `WORKSPACE_ACTION`, `apply` or `destroy`, while the server keeps running:

- `apply` creates the bucket `ws-<id>-state` through `weed shell s3.bucket.create` and turns versioning on with the admin identity.
- `apply` creates the identity `ws-<id>-provision` with exactly `Read`, `Write` and `List` on that bucket: no `Admin`, no `WriteAcp`, no `Tagging`, no other bucket.
  The identity is rebuilt from the workspace id on every assembly, so a record cannot widen its own actions.
- The keys are generated once.
  They live in `identities.d/ws-<id>.json`, mode `0600`, in the role's volume directory, and in OpenBao at `tenant/data/ws-<id>-provision/s3` as `access_key` and `secret_key`, which the provision runner reads.
  A second `apply` keeps the keys of the record, and after a restore without `identities.d` it takes them back from OpenBao.
- `destroy` refuses while the bucket still holds a `.tfstate` object, so the servers of the workspace have to be destroyed first.
  It then removes the identity and reloads, waits until the old keys are refused, and deletes the bucket with every object version through `s3.bucket.delete`.
  A missing record or bucket counts as removed, so a stopped `destroy` finishes when it runs again.
  The OpenBao copy of the keys is erased by the `destroy` of `web-app-openbao` with every other secret of the workspace.

### Fail-closed reload

With no identity configured, the S3 gateway allows every request.
`s3.json` is therefore assembled from the inventory identities of `s3.json.j2` plus every record of `identities.d`, and the assembly fails when it holds no `admin` identity with the `Admin` action, so the file is never empty.
The container mounts the directory `s3/` that holds `s3.json` read-only at `/etc/seaweedfs/s3`, never the file alone: a single-file bind keeps the inode it had at start, so a renamed file would never reach the container.
The deploy and `apply` render the new file next to the old one, rename it into place and send `SIGHUP`, on which the gateway reads the file again; the container is not restarted.
Every deploy fails unless an unsigned request is refused with `403`.
The filer-stored identity configuration stays unused, because a server started without the file would allow every request until the filer copy loads.

### Slot maximum

Workspace buckets grow one volume at a time (`fs.configure -locationPrefix=/buckets/ws- -volumeGrowthCount=1`).
`-volume.max` reserves one slot per workspace up to `services.seaweedfs.workspaces.max` in `meta/services.yml`, on top of the slots of the consumer buckets.
`apply` refuses a workspace beyond that maximum with a message that names the key.

### Version floor

The lock of OpenTofu's S3 backend is a conditional `PutObject` with `If-None-Match: *` on a versioned bucket.
Up to 4.52 such a write could be accepted but unreadable after a racing `DELETE` ([seaweedfs#12453](https://github.com/seaweedfs/seaweedfs/issues/12453)), so the pin stays at 4.53 or later, and a unit test holds that floor.

## Features

- **S3-compatible API:** Standard S3 SDKs and CLIs work against the gateway for uploads, media, attachments, and exports.
- **Central object-store service:** One shared instance serves all consuming web-app roles, mirroring the shared database pattern.
- **Per-consumer isolation:** Every consumer receives its own identity and bucket with bucket-scoped actions only.
- **Separable console:** The browser interfaces deploy and scale independently of the storage engine.
- **Embedded mode:** Roles that opt out of the shared instance run a private storage-only container inside their own compose network.

## Further Resources

- [SeaweedFS on GitHub](https://github.com/seaweedfs/seaweedfs)
- [SeaweedFS Wiki](https://github.com/seaweedfs/seaweedfs/wiki)
- [Amazon S3 API](https://aws.amazon.com/s3/)
