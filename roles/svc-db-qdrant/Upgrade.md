# Qdrant Docker Upgrade

This guide explains how to safely upgrade the Qdrant Docker container between versions.

---

## Important

Qdrant storage is forward-compatible within a major line but a major upgrade may require a snapshot/restore. Pin `services.qdrant.version` and test before rolling forward in production.

## Backup

Create a snapshot of every collection first (`POST /collections/{name}/snapshots`).

## Restore

Bump the version, redeploy, then restore the snapshots into the new instance.

## References

- [Qdrant Snapshots](https://qdrant.tech/documentation/concepts/snapshots/)
- [Qdrant Docker Image](https://hub.docker.com/r/qdrant/qdrant)
