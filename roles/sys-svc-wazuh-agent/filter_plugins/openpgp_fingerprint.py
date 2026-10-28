import base64
import hashlib

from ansible.errors import AnsibleFilterError

PUBLIC_KEY_TAG = 6


def _packet(data):
    first = data[0]
    if not first & 0x80:
        raise AnsibleFilterError("openpgp_fingerprint: not an OpenPGP packet")
    if first & 0x40:
        tag, length_byte = first & 0x3F, data[1]
        if length_byte < 192:
            return tag, data[2 : 2 + length_byte]
        if length_byte < 224:
            length = ((length_byte - 192) << 8) + data[2] + 192
            return tag, data[3 : 3 + length]
        if length_byte == 255:
            length = int.from_bytes(data[2:6], "big")
            return tag, data[6 : 6 + length]
        raise AnsibleFilterError("openpgp_fingerprint: partial body lengths are not a public key")
    length_type = first & 0x03
    if length_type == 3:
        raise AnsibleFilterError("openpgp_fingerprint: indeterminate packet length")
    tag, size = (first >> 2) & 0x0F, (1, 2, 4)[length_type]
    length = int.from_bytes(data[1 : 1 + size], "big")
    return tag, data[1 + size : 1 + size + length]


def openpgp_fingerprint(armored):
    """Return the fingerprint of the primary key in an ASCII-armored OpenPGP public key.

    Args:
        armored: the key as text, e.g. from ``slurp`` and ``b64decode``.

    Returns:
        The v4 fingerprint as 40 upper-case hex digits, the form ``gpg --with-colons`` prints in its ``fpr`` line.

    Raises:
        AnsibleFilterError: the text is no armored public key or its primary key is not version 4.
    """
    lines = armored.strip().splitlines()
    try:
        start = lines.index("-----BEGIN PGP PUBLIC KEY BLOCK-----")
        end = lines.index("-----END PGP PUBLIC KEY BLOCK-----")
    except ValueError as error:
        raise AnsibleFilterError("openpgp_fingerprint: no armored public key block") from error
    body = lines[start + 1 : end]
    body = body[body.index("") + 1 :] if "" in body else body
    data = base64.b64decode("".join(line for line in body if not line.startswith("=")))
    tag, packet = _packet(data)
    if tag != PUBLIC_KEY_TAG or not packet or packet[0] != 4:
        raise AnsibleFilterError("openpgp_fingerprint: the first packet is no version 4 public key")
    return hashlib.sha1(b"\x99" + len(packet).to_bytes(2, "big") + packet).hexdigest().upper()  # noqa: S324 - OpenPGP v4 fingerprints are defined as SHA-1


class FilterModule:
    def filters(self):
        return {"openpgp_fingerprint": openpgp_fingerprint}
