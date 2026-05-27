def littlejs_href(example, protocol, domain):
    """
    Build correct LittleJS example URL based on whether it is a full project
    or a single-file example.

    :param example: dict with keys 'is_project' and 'file'
    :param protocol: http or https
    :param domain: the domain to use (e.g. littlejs.example.com)
    :return: string URL
    """

    file = example.get("file")
    is_project = example.get("is_project", False)

    if not file:
        return "#"

    # Full examples: always absolute URL
    if is_project:
        return f"{protocol}://{domain}/examples/{file}/"

    # Non-full shorts: use custom runner without example browser overhead
    return f"{protocol}://{domain}/examples/shorts/run.html?file={file}"


class FilterModule:
    def filters(self):
        return {"littlejs_href": littlejs_href}
