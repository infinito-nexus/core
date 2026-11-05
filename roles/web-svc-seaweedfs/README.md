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

Every vhost of a shared consumer marked `public` also serves its bucket under `/_infinito/objstore/<bucket>/`, and `lookup('objstore', application_id, 'relative_url')` returns that host-relative base for URLs a browser loads.
The route passes `GET` and `HEAD` for object keys only: it answers `404` for a path ending in `/`, drops the query string and the `Authorization` and `Cookie` headers, and sends the request over the loopback to the `api.seaweedfs.s3.*` vhost.
Responses carry `X-Content-Type-Options: nosniff` and a `sandbox` Content Security Policy.
A consumer without `public: true` or in embedded mode gets an empty `relative_url` and no route.

In embedded mode (`shared: false`) a consumer's compose stack receives a storage-only SeaweedFS container without UI or published ports.
The embedded S3 listener starts without identities and accepts unauthenticated requests until the background `s3.configure` grant at startup registers the consumer identity; from then on it authenticates against that identity.
Embedded buckets carry no `DenyAnonymousRead` statement because the listener publishes no port, so the container MUST stay confined to the consumer's isolated compose network.

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
