# nocheck: mirrored-unit-test - runs inside `odoo shell`, which provides `env` and a live registry; the framework is not installable outside the Odoo image
import base64
import hashlib
import json

from lxml import etree

SHELL = globals()
env = SHELL["env"]
PAYLOAD = json.loads(base64.b64decode(SHELL["DESIGN_PAYLOAD"]))

STATE_KEY = "infinito.design_state"
APP_NAME_KEY = "web.web_app_name"
THEME_ROOT = "/_custom/infinito"
THEME_URL = THEME_ROOT + "/design/{bundle}.css"
WEBSITE_BUNDLE = "web.assets_frontend"
VIEW_KEY = "infinito_design.web_layout"
DEFAULT_WEBSITE_NAME = "My Website"


def digest(value):
    """Return the mark stored for a value.

    Args:
        value: bytes or str.

    Returns:
        A short hex digest.
    """
    raw = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def read(record, field):
    """Return the stored value of a field in a comparable form.

    Args:
        record: recordset of one record.
        field: field name.

    Returns:
        The content bytes of a binary field, the text of any other field.
    """
    value = record[field]
    if record._fields[field].type == "binary":
        return value.content if value else b""
    return value or ""


def write(record, field, value):
    """Write a field and drop the cached value, so the next read sees what the model stored.

    Args:
        record: recordset of one record.
        field: field name.
        value: content bytes for a binary field, text for any other field.
    """
    if record._fields[field].type == "binary":
        value = base64.b64encode(value).decode("ascii")
    record[field] = value
    record.flush_recordset()
    record.invalidate_recordset()


def converge_field(state, record, field, wanted, default):
    """Write one branding field the design owns, or hand it back.

    Args:
        state: ``{key: {"input", "stored"}}`` of the last run, updated in
            place. ``stored`` marks the value the model kept after the last
            write of the design; an empty ``input`` marks a restored default.
        record: recordset of one record.
        field: field name.
        wanted: value to write; empty to put the upstream default back.
        default: upstream default of the field.

    Returns:
        True when the field was written. A value that is neither the upstream
        default nor the last write of the design belongs to somebody else and
        stays untouched.
    """
    key = f"{record._name}.{field}"
    current = digest(read(record, field))
    entry = state.get(key)
    ours = entry is not None and entry["stored"] == current
    if not ours and (not wanted or current != digest(default)):
        state.pop(key, None)
        return False
    target = digest(wanted) if wanted else ""
    if ours and entry["input"] == target:
        return False
    write(record, field, wanted or default)
    state[key] = {"input": target, "stored": digest(read(record, field))}
    return True


def converge_parameter(state, key, wanted):
    """Set a system parameter the design owns, or remove it again.

    Args:
        state: ``{key: applied value}`` of the last run, updated in place.
        key: parameter key.
        wanted: value to set; empty to remove what the design set.

    Returns:
        True when the parameter changed. A value somebody else set stays.
    """
    record = env["ir.config_parameter"].sudo().search([("key", "=", key)], limit=1)
    current = record.value or ""
    ours = key in state and state[key] == current
    if current and not ours:
        state.pop(key, None)
        return False
    if not wanted:
        state.pop(key, None)
        record.unlink()
        return bool(current)
    state[key] = wanted
    if current == wanted:
        return False
    if record:
        record.value = wanted
    else:
        record.create({"key": key, "value": wanted})
    return True


def website_theme_customised():
    """Tell whether somebody customised the website theme in the builder.

    Returns:
        True when an asset entry points at a customised file that is not a
        sheet of the design. The builder stores every theme change that way,
        and the frontend sheet of the design would paint over it.
    """
    assets = env["ir.asset"].sudo().with_context(active_test=False)
    return bool(
        assets.search_count(
            [("path", "=like", "/_custom/%"), "!", ("path", "=like", f"{THEME_ROOT}/%")]
        )
    )


def converge_theme(bundle, css):
    """Create, update or remove the theme stylesheet of one asset bundle.

    Args:
        bundle: asset bundle the stylesheet is appended to.
        css: stylesheet text; empty to remove the stylesheet and its bundle
            entry. Both are found through the URL only the design uses.

    Returns:
        True when an attachment or an asset record changed. A changed
        stylesheet gets a new bundle entry, because creating one is what makes
        the registry drop the compiled bundle.
    """
    url = THEME_URL.format(bundle=bundle)
    attachment = env["ir.attachment"].sudo().search([("url", "=", url)], limit=1)
    assets = (
        env["ir.asset"]
        .sudo()
        .with_context(active_test=False)
        .search([("path", "=", url)])
    )
    if not css:
        changed = bool(attachment or assets)
        assets.unlink()
        attachment.unlink()
        return changed
    raw = css.encode("utf-8")
    fresh = not attachment or attachment.raw.content != raw
    if not attachment:
        attachment.create(
            {
                "name": f"infinito-design-{bundle}.css",
                "type": "binary",
                "mimetype": "text/css",
                "url": url,
                "public": True,
                "raw": raw,
            }
        )
    elif fresh:
        attachment.raw = raw
    kept = (
        assets.browse()
        if fresh
        else assets.filtered(lambda asset: asset.bundle == bundle and asset.active)[:1]
    )
    stale = assets - kept
    stale.unlink()
    if not kept:
        env["ir.asset"].sudo().create(
            {
                "name": f"infinito design: {bundle}",
                "bundle": bundle,
                "directive": "append",
                "path": url,
                "sequence": 999,
            }
        )
    return bool(fresh or stale or not kept)


def converge_layout(state, title, icon):
    """Create, update or remove the inherited view that brands the backend shell.

    Args:
        state: state of the last run, updated in place under the view key.
        title: default document title of the backend; empty to keep upstream's.
        icon: URL of the backend favicon; empty to keep upstream's.

    Returns:
        True when the view changed. Only the view with the key of the design
        is touched.
    """
    view = (
        env["ir.ui.view"]
        .sudo()
        .with_context(active_test=False)
        .search([("key", "=", VIEW_KEY)], limit=1)
    )
    if not title and not icon:
        state.pop(VIEW_KEY, None)
        view.unlink()
        return bool(view)
    data = etree.Element("data")
    if title:
        node = etree.SubElement(data, "xpath", expr="//title", position="attributes")
        etree.SubElement(node, "attribute", name="t-out").text = f"title or {title!r}"
    if icon:
        node = etree.SubElement(
            data, "xpath", expr="//link[@rel='shortcut icon']", position="attributes"
        )
        etree.SubElement(
            node, "attribute", name="t-att-href"
        ).text = f"x_icon or {icon!r}"
    arch = etree.tostring(data, encoding="unicode")
    if view and state.get(VIEW_KEY) == digest(arch):
        return False
    state[VIEW_KEY] = digest(arch)
    if view:
        view.arch = arch
    else:
        view.create(
            {
                "name": "infinito design: web layout",
                "key": VIEW_KEY,
                "type": "qweb",
                "mode": "extension",
                "inherit_id": env.ref("web.layout").id,
                "priority": 99,
                "arch": arch,
            }
        )
    return True


parameters = env["ir.config_parameter"].sudo()
state_record = parameters.search([("key", "=", STATE_KEY)], limit=1)
before = state_record.value or "{}"
state = json.loads(before)
title = PAYLOAD["title"]
logo = base64.b64decode(PAYLOAD["logo"])
favicon = base64.b64decode(PAYLOAD["favicon"])
website = (
    env["website"].sudo().search([], limit=1, order="id") if "website" in env else None
)

results = [
    converge_theme(
        bundle, "" if bundle == WEBSITE_BUNDLE and website_theme_customised() else css
    )
    for bundle, css in sorted(PAYLOAD["themes"].items())
]
results.append(converge_parameter(state, APP_NAME_KEY, title))
icon = ""
if website:
    results += [
        converge_field(state, website, "name", title, DEFAULT_WEBSITE_NAME),
        converge_field(state, website, "logo", logo, website._default_logo()),
        converge_field(state, website, "favicon", favicon, website._default_favicon()),
    ]
    if favicon:
        icon = f"/web/image/website/{website.id}/favicon?unique={digest(favicon)}"
results.append(converge_layout(state, title, icon))

after = json.dumps(state, sort_keys=True)
if after != before:
    if state_record:
        state_record.value = after
    else:
        state_record.create({"key": STATE_KEY, "value": after})
env.cr.commit()
print("DESIGN_CHANGED" if any(results) or after != before else "DESIGN_UNCHANGED")
