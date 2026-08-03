# Nextcloud config templates

Every `*.j2` here is rendered to the host-mounted config directory and merged
into `$CONFIG` by `zzz-infinito.config.php`, which Nextcloud applies after
`config.php`. Values set here therefore win.

Put system configuration here rather than calling `occ config:system:set`: the
occ path takes an exclusive lock on `config.php`, which is a single NFS-shared
file behind every replica in swarm mode, while this path is read-only.
