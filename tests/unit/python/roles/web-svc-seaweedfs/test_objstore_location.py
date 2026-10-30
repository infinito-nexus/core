from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = "roles/web-svc-seaweedfs/templates/nginx/locations.conf.j2"
VHOSTS = (
    "roles/sys-svc-proxy/templates/vhost/basic.conf.j2",
    "roles/sys-svc-proxy/templates/vhost/ws_generic.conf.j2",
)
CONSUMER = "web-app-foo"
PUBLIC_CONSUMER = {
    "bucket": "foo",
    "relative_url": "/_infinito/objstore/foo",
    "upstream_scheme": "https",
    "upstream_domain": "api.seaweedfs.s3.example.com",
}
CLEARNET = "foo.example.com"
ONION = "foo.abcdefghij.onion"


def _render(objstore: dict, application_id: str, domain: str) -> str:
    """
    Args:
        objstore: what lookup('objstore', 'web-app-foo') answers; every other role answers an empty relative_url.
        application_id: the role whose vhost is rendered.
        domain: the vhost being rendered.

    Returns:
        The rendered nginx fragment.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.globals["lookup"] = lambda name, app: (
        objstore if (name, app) == ("objstore", CONSUMER) else {"relative_url": ""}
    )
    return env.get_template(TEMPLATE).render(
        application_id=application_id, domain=domain
    )


def _outer_location(rendered: str) -> str:
    match = re.search(
        r"location \^~ /_infinito/objstore/foo/ \{(?P<body>.*)\n  \}",
        rendered,
        re.DOTALL,
    )
    assert match, rendered
    return match.group("body")


def _limited_methods(body: str) -> set[str]:
    match = re.search(r"limit_except ([A-Z ]+)\{\s*deny all;\s*\}", body)
    assert match, body
    return set(match.group(1).split())


class TestObjstoreSameOriginLocation(unittest.TestCase):
    def test_the_route_is_rendered_on_the_clearnet_and_the_onion_vhost(self):
        clearnet = _render(PUBLIC_CONSUMER, CONSUMER, CLEARNET)
        onion = _render(PUBLIC_CONSUMER, CONSUMER, ONION)

        self.assertIn("location ^~ /_infinito/objstore/foo/ {", clearnet)
        self.assertEqual(
            clearnet,
            onion,
            "a page on either network dials the same relative path, so both "
            "vhosts must answer it alike",
        )

    def test_only_get_and_head_pass(self):
        body = _outer_location(_render(PUBLIC_CONSUMER, CONSUMER, ONION))

        self.assertEqual(
            _limited_methods(body),
            {"GET"},
            "limit_except GET admits GET and HEAD only; PUT, POST and DELETE "
            "would reach the S3 write API",
        )

    def test_the_bucket_listing_and_s3_subresources_are_closed(self):
        body = _outer_location(_render(PUBLIC_CONSUMER, CONSUMER, ONION))

        self.assertRegex(
            body,
            r"location ~ /\$ \{\s*return 404;\s*\}",
            "a path ending in / is ListObjects on the bucket or a directory",
        )
        self.assertIn(
            'set $args "";',
            body,
            "?list-type, ?acl, ?policy, ?tagging and presigned queries must "
            "never reach the store",
        )

    def test_the_route_is_bound_to_the_consumer_bucket_anonymously(self):
        body = _outer_location(_render(PUBLIC_CONSUMER, CONSUMER, ONION))

        self.assertIn("proxy_pass https://127.0.0.1/foo/;", body)
        self.assertIn("proxy_set_header Host api.seaweedfs.s3.example.com;", body)
        self.assertIn('proxy_set_header Authorization "";', body)
        self.assertIn('proxy_set_header Cookie "";', body)
        self.assertIn("proxy_hide_header X-Powered-By;", body)
        self.assertIn('Content-Security-Policy "sandbox;', body)
        self.assertIn('X-Content-Type-Options "nosniff"', body)

    def test_a_consumer_without_a_relative_url_gets_no_route(self):
        rendered = _render({**PUBLIC_CONSUMER, "relative_url": ""}, CONSUMER, ONION)

        self.assertNotIn("location", rendered)

    def test_a_role_without_an_object_store_gets_no_route(self):
        rendered = _render(PUBLIC_CONSUMER, "web-app-bar", CLEARNET)

        self.assertNotIn("location", rendered)

    def test_every_generic_vhost_includes_the_route_outside_any_branch(self):
        include = f"{{% include '{TEMPLATE}' %}}"
        for vhost in VHOSTS:
            text = read_text(str(PROJECT_ROOT / vhost))
            with self.subTest(vhost=vhost):
                self.assertIn(include, text)
                before = text.split(include, 1)[0]
                depth = len(re.findall(r"\{%-?\s*if\b", before)) - len(
                    re.findall(r"\{%-?\s*endif\b", before)
                )
                self.assertEqual(
                    depth,
                    0,
                    "an include inside a branch would skip the route on some vhosts",
                )


if __name__ == "__main__":
    unittest.main()
