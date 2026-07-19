"""
Ansible filter plugin that safely joins URL components from a list.
- Requires a valid '<scheme>://' in the first element (any RFC-3986-ish scheme)
- Preserves the double slash after the scheme, collapses other duplicate slashes
- Supports query parts introduced by elements starting with '?' or '&'
  * first query element uses '?', subsequent use '&' (regardless of given prefix)
  * each query element must be exactly one 'key=value' pair
  * query elements may only appear after path elements; once query starts, no more path parts
- Raises specific AnsibleFilterError messages for common misuse
"""

import re

from ansible.errors import AnsibleFilterError

_SCHEME_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*://)(.*)$")
_QUERY_PAIR_RE = re.compile(
    r"^[^&=?#]+=[^&?#]*$"
)  # key=value (no '&', no extra '?' or '#')


def _to_str_or_error(obj, index):
    """Cast to str, raising a specific AnsibleFilterError with index context."""
    try:
        return str(obj)
    except Exception as e:
        raise AnsibleFilterError(
            f"url_join: unable to convert part at index {index} to string: {e}"
        ) from e


def url_join(parts):
    """
    Join a list of URL parts, URL-aware (scheme, path, query).

    Args:
        parts (list|tuple): URL segments. First element MUST include '<scheme>://'.
            Path elements are plain strings.
            Query elements must start with '?' or '&' and contain exactly one 'key=value'.

    Returns:
        str: Joined URL.

    Raises:
        AnsibleFilterError: with specific, descriptive messages.
    """
    # --- basic input validation ---
    if parts is None:
        raise AnsibleFilterError("url_join: parts must be a non-empty list; got None")
    if not isinstance(parts, (list, tuple)):
        raise AnsibleFilterError(
            f"url_join: parts must be a list/tuple; got {type(parts).__name__}"
        )
    if len(parts) == 0:
        raise AnsibleFilterError("url_join: parts must be a non-empty list")

    # --- first element must carry a scheme ---
    first_raw = parts[0]
    if first_raw is None:
        raise AnsibleFilterError(
            "url_join: first element must include a scheme like 'https://'; got None"
        )

    first_str = _to_str_or_error(first_raw, 0)
    m = _SCHEME_RE.match(first_str)
    if not m:
        raise AnsibleFilterError(
            "url_join: first element must start with '<scheme>://', e.g. 'https://example.com'; "
            f"got '{first_str}'"
        )

    scheme = m.group(1)  # e.g., 'https://', 'ftp://', 'myapp+v1://'
    after_scheme = m.group(2).lstrip(
        "/"
    )  # strip only leading slashes right after scheme

    # --- iterate parts: collect path parts until first query part; then only query parts allowed ---
    path_parts = []
    query_pairs = []
    in_query = False

    for i, p in enumerate(parts):
        if p is None:
            # skip None silently (consistent with path_join-ish behavior)
            continue

        s = _to_str_or_error(p, i)

        # disallow additional scheme in later parts
        if i > 0 and "://" in s:
            raise AnsibleFilterError(
                f"url_join: only the first element may contain a scheme; part at index {i} "
                f"looks like a URL with scheme ('{s}')."
            )

        # first element: replace with remainder after scheme and continue
        if i == 0:
            s = after_scheme

        # check if this is a query element (starts with ? or &)
        if s.startswith(("?", "&")):
            in_query = True
            raw_pair = s[1:]  # strip the leading ? or &
            if raw_pair == "":
                raise AnsibleFilterError(
                    f"url_join: query element at index {i} is empty; expected '?key=value' or '&key=value'"
                )
            # Disallow multiple pairs in a single element; enforce exactly one key=value
            if "&" in raw_pair:
                raise AnsibleFilterError(
                    f"url_join: query element at index {i} must contain exactly one 'key=value' pair "
                    f"without '&'; got '{s}'"
                )
            if not _QUERY_PAIR_RE.match(raw_pair):
                raise AnsibleFilterError(
                    f"url_join: query element at index {i} must match 'key=value' (no extra '?', '&', '#'); got '{s}'"
                )
            query_pairs.append(raw_pair)
        else:
            # non-query element
            if in_query:
                # once query started, no more path parts allowed
                raise AnsibleFilterError(
                    f"url_join: path element found at index {i} after query parameters started; "
                    f"query parts must come last"
                )
            # normal path part: strip slashes to avoid duplicate '/'
            path_parts.append(s.strip("/"))

    # normalize path: remove empty chunks
    path_parts = [p for p in path_parts if p != ""]

    # --- build result ---
    # path portion
    if path_parts:
        joined_path = "/".join(path_parts)
        base = scheme + joined_path
    else:
        # no path beyond scheme
        base = scheme

    # query portion
    if query_pairs:
        base = base + "?" + "&".join(query_pairs)

    return base


class FilterModule:
    def filters(self):
        return {
            "url_join": url_join,
        }
