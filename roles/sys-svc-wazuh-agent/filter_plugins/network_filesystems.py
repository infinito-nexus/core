NETWORK_FSTYPES = frozenset(
    {
        "9p",
        "afs",
        "ceph",
        "cifs",
        "davfs",
        "glusterfs",
        "lustre",
        "nfs",
        "nfs4",
        "rclone",
        "s3fs",
        "smb3",
        "smbfs",
        "sshfs",
    }
)


def network_filesystems(results):
    """Return the checkouts that live on a network filesystem.

    Args:
        results: the ``results`` of a looped ``findmnt --output FSTYPE --target <item>`` command.

    Returns:
        One ``"<path> (<fstype>)"`` per result whose filesystem type is a network one; ``fuse.<type>`` counts as ``<type>``.
    """
    found = []
    for result in results:
        fstype = result["stdout"].strip()
        if fstype.removeprefix("fuse.") in NETWORK_FSTYPES:
            found.append(f"{result['item']} ({fstype})")
    return found


class FilterModule:
    def filters(self):
        return {"network_filesystems": network_filesystems}
