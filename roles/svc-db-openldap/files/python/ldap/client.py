"""Speak just enough LDAPv3 to bind, search and add values, with the standard library only."""

import socket
import ssl
from urllib.parse import unquote, urlsplit

TIMEOUT_SECONDS = 10

BOOLEAN = 0x01
INTEGER = 0x02
OCTET_STRING = 0x04
ENUMERATED = 0x0A
SEQUENCE = 0x30
SET = 0x31
BIND_REQUEST = 0x60
BIND_RESPONSE = 0x61
SEARCH_REQUEST = 0x63
SEARCH_RESULT_ENTRY = 0x64
SEARCH_RESULT_DONE = 0x65
MODIFY_REQUEST = 0x66
MODIFY_RESPONSE = 0x67
SIMPLE_AUTHENTICATION = 0x80
FILTER_EQUALITY = 0xA3
FILTER_PRESENT = 0x87

LDAP_VERSION = 3
SCOPE_BASE = 0
SCOPE_ONE_LEVEL = 1
DEREF_NEVER = 0
SIZE_UNLIMITED = 0
MODIFY_ADD = 0
SUCCESS = 0
TYPE_OR_VALUE_EXISTS = 20
DISCONNECTION_NOTICE_ID = 0


class DirectoryError(Exception):
    """The directory refused an operation or answered something unexpected."""


class SocketMissingError(DirectoryError):
    """No ``ldapi`` socket exists at the path: OpenLDAP does not run on this node."""


def encode_length(length):
    """Return the BER length octets.

    Args:
        length: number of content octets.
    """
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def tlv(tag, value):
    """Return one BER element.

    Args:
        tag: the identifier octet.
        value: the content octets.
    """
    return bytes([tag]) + encode_length(len(value)) + value


def number(tag, value):
    """Return a BER INTEGER or ENUMERATED element.

    Args:
        tag: ``INTEGER`` or ``ENUMERATED``.
        value: the non-negative number.
    """
    return tlv(tag, value.to_bytes((value.bit_length() + 8) // 8, "big", signed=True))


def text(value):
    """Return an OCTET STRING element holding UTF-8 text.

    Args:
        value: the string.
    """
    return tlv(OCTET_STRING, value.encode("utf-8"))


def decode(data, offset):
    """Return ``(tag, content, next offset)`` of the element at ``offset``.

    Args:
        data: the encoded octets.
        offset: where the element starts.
    """
    if offset + 2 > len(data):
        raise DirectoryError("truncated element")
    tag = data[offset]
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or offset + count > len(data):
            raise DirectoryError("malformed element length")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    end = offset + length
    if end > len(data):
        raise DirectoryError("truncated element")
    return tag, data[offset:end], end


def children(data):
    """Return the ``(tag, content)`` pairs a constructed element holds.

    Args:
        data: the content octets of the constructed element.
    """
    items = []
    offset = 0
    while offset < len(data):
        tag, value, offset = decode(data, offset)
        items.append((tag, value))
    return items


def result_code(content):
    """Return the resultCode of an LDAPResult.

    Args:
        content: the content octets of a response that carries an LDAPResult.
    """
    tag, value = children(content)[0]
    if tag != ENUMERATED:
        raise DirectoryError("response without a result code")
    return int.from_bytes(value, "big")


def parse_entry(content):
    """Return ``(dn, {lowercased attribute: [values]})`` of a SearchResultEntry, values decoded with ``surrogateescape``.

    Args:
        content: the content octets of the SearchResultEntry.
    """
    (_, dn), (_, attributes) = children(content)[:2]
    values = {}
    for _, attribute in children(attributes):
        (_, name), (_, entries) = children(attribute)[:2]
        values[name.decode("utf-8").lower()] = [
            value.decode("utf-8", "surrogateescape") for _, value in children(entries)
        ]
    return dn.decode("utf-8"), values


def raw(value):
    """Return the original octets of a value ``parse_entry`` decoded.

    Args:
        value: one attribute value.
    """
    return value.encode("utf-8", "surrogateescape")


def equality(attribute, value):
    """Return an equalityMatch filter.

    Args:
        attribute: the attribute description.
        value: the asserted value, unescaped.
    """
    return tlv(FILTER_EQUALITY, text(attribute) + text(value))


def present(attribute):
    """Return a present filter.

    Args:
        attribute: the attribute description.
    """
    return tlv(FILTER_PRESENT, attribute.encode("utf-8"))


def normalize_dn(dn):
    """Return a DN comparable regardless of case and spacing after commas.

    Args:
        dn: the DN.
    """
    return ",".join(part.strip() for part in dn.split(",")).lower()


def unix_connection(path):
    """Return a stream socket connected to a Unix domain socket.

    Args:
        path: the filesystem path of the socket.

    Raises:
        SocketMissingError: nothing exists at the path.
        OSError: the socket exists but does not answer.
    """
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        raw.settimeout(TIMEOUT_SECONDS)
        raw.connect(path)
    except FileNotFoundError as error:
        raw.close()
        raise SocketMissingError(
            f"no directory socket at {path} on this node"
        ) from error
    except OSError:
        raw.close()
        raise
    return raw


class Connection:
    """One LDAPv3 session over a plain, TLS or Unix domain socket; a search before any bind is anonymous.

    Args:
        uri: ``ldap://`` or ``ldaps://`` URI of the directory, or ``ldapi://``
            with the percent-encoded path of its Unix domain socket.
    """

    def __init__(self, uri):
        parts = urlsplit(uri)
        self.message_id = 0
        if parts.scheme == "ldapi" and parts.netloc:
            self.socket = unix_connection(unquote(parts.netloc))
            return
        if parts.scheme not in ("ldap", "ldaps") or not parts.hostname:
            raise DirectoryError(f"unsupported directory URI {uri!r}")
        port = parts.port or (636 if parts.scheme == "ldaps" else 389)
        raw = socket.create_connection((parts.hostname, port), timeout=TIMEOUT_SECONDS)
        if parts.scheme == "ldaps":
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            raw = context.wrap_socket(raw, server_hostname=parts.hostname)
        self.socket = raw

    def close(self):
        self.socket.close()

    def read(self, count):
        """Return exactly ``count`` octets from the socket.

        Args:
            count: number of octets to read.
        """
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self.socket.recv(count - len(chunks))
            if not chunk:
                raise DirectoryError("the directory closed the connection")
            chunks.extend(chunk)
        return bytes(chunks)

    def send(self, operation):
        """Send one request and return its message ID.

        Args:
            operation: the encoded protocolOp.
        """
        self.message_id += 1
        self.socket.sendall(tlv(SEQUENCE, number(INTEGER, self.message_id) + operation))
        return self.message_id

    def message(self):
        """Return ``(message ID, (tag, content))`` of the next LDAPMessage."""
        head = self.read(2)
        if head[0] != SEQUENCE:
            raise DirectoryError("answer is no LDAPMessage")
        length = head[1]
        if length & 0x80:
            length = int.from_bytes(self.read(length & 0x7F), "big")
        items = children(self.read(length))
        return int.from_bytes(items[0][1], "big"), items[1]

    def response(self, message_id):
        """Return ``(tag, content)`` of the next protocolOp answering ``message_id``.

        Args:
            message_id: the ID of the request the answer belongs to.
        """
        answered, operation = self.message()
        while answered != message_id:
            if answered == DISCONNECTION_NOTICE_ID:
                raise DirectoryError("the directory announced a disconnection")
            answered, operation = self.message()
        return operation

    def bind(self, dn, password):
        """Return the result code of a simple bind.

        Args:
            dn: the DN to bind as.
            password: its password.
        """
        credentials = tlv(SIMPLE_AUTHENTICATION, password.encode("utf-8"))
        message_id = self.send(
            tlv(BIND_REQUEST, number(INTEGER, LDAP_VERSION) + text(dn) + credentials)
        )
        tag, content = self.response(message_id)
        if tag != BIND_RESPONSE:
            raise DirectoryError("bind answered with another operation")
        return result_code(content)

    def search(self, base, scope, search_filter, attributes):
        """Return the ``(dn, values)`` entries a search finds.

        Args:
            base: the base DN.
            scope: ``SCOPE_BASE`` or ``SCOPE_ONE_LEVEL``.
            search_filter: the encoded filter.
            attributes: the attribute descriptions to return.
        """
        request = (
            text(base)
            + number(ENUMERATED, scope)
            + number(ENUMERATED, DEREF_NEVER)
            + number(INTEGER, SIZE_UNLIMITED)
            + number(INTEGER, TIMEOUT_SECONDS)
            + tlv(BOOLEAN, b"\x00")
            + search_filter
            + tlv(SEQUENCE, b"".join(text(attribute) for attribute in attributes))
        )
        message_id = self.send(tlv(SEARCH_REQUEST, request))
        entries = []
        tag, content = self.response(message_id)
        while tag != SEARCH_RESULT_DONE:
            if tag == SEARCH_RESULT_ENTRY:
                entries.append(parse_entry(content))
            tag, content = self.response(message_id)
        code = result_code(content)
        if code != SUCCESS:
            raise DirectoryError(f"search answered result code {code}")
        return entries

    def add_values(self, dn, additions):
        """Return the result code of one modify that adds values to an entry.

        Args:
            dn: the DN of the entry.
            additions: mapping of attribute description to the values to add.
        """
        changes = b"".join(
            tlv(
                SEQUENCE,
                number(ENUMERATED, MODIFY_ADD)
                + tlv(
                    SEQUENCE,
                    text(attribute)
                    + tlv(SET, b"".join(text(value) for value in values)),
                ),
            )
            for attribute, values in additions.items()
        )
        message_id = self.send(tlv(MODIFY_REQUEST, text(dn) + tlv(SEQUENCE, changes)))
        tag, content = self.response(message_id)
        if tag != MODIFY_RESPONSE:
            raise DirectoryError("modify answered with another operation")
        return result_code(content)
