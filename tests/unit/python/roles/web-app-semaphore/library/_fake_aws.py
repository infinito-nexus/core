from __future__ import annotations

import importlib.util
import json
import re
import sys
from urllib.parse import parse_qsl, quote, urlsplit

from utils import aws_api
from utils.cache.files import PROJECT_ROOT

LIBRARY = PROJECT_ROOT / "roles" / "web-app-semaphore" / "library"
ADMIN = {
    "access_key_id": "AKIAADMINEXAMPLE0001",
    "secret_access_key": "admin-secret-that-never-travels",
}
IAM_NS = f"{aws_api.IAM['url']}/doc/{aws_api.IAM_VERSION}/"
ROUTE53_NS = f"{aws_api.ROUTE53['url']}/doc/2013-04-01/"
IAM_HOST = urlsplit(aws_api.IAM["url"]).netloc
ROUTE53_HOST = urlsplit(aws_api.ROUTE53["url"]).netloc
AUTHORIZATION = re.compile(
    r"^AWS4-HMAC-SHA256 Credential=(?P<key>[^/]+)/(?P<day>\d{8})/(?P<region>[^/]+)/"
    r"(?P<service>[^/]+)/aws4_request, SignedHeaders=(?P<signed>[a-z0-9;-]+), "
    r"Signature=[0-9a-f]{64}$"
)
PAGE = 1
KEY_LIMIT = 2
CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def load(name):
    """Args:
        name: the module file name below the role's ``library/``, without ``.py``.

    Returns:
        The loaded module, with ``ansible.module_utils.aws_api`` served from
        ``utils/aws_api.py`` as Ansible bundles it.
    """
    sys.modules.setdefault("ansible.module_utils.aws_api", aws_api)
    spec = importlib.util.spec_from_file_location(
        f"web_app_semaphore_{name}", str(LIBRARY / f"{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _xml(tag, inner, namespace):
    return f'<{tag} xmlns="{namespace}">{inner}</{tag}>'.encode()


def _error(status, code, namespace):
    inner = (
        f"<Error><Type>Sender</Type><Code>{code}</Code>"
        f"<Message>{code} from the fake</Message></Error><RequestId>r</RequestId>"
    )
    return status, _xml("ErrorResponse", inner, namespace)


def _labels(name):
    return list(reversed(name.lower().rstrip(".").split(".")))


class FakeAws:
    """Args:
    credentials: the admin credential the fake accepts.
    """

    def __init__(self, credentials=ADMIN):
        self.credentials = credentials
        self.users = {}
        self.zones = []
        self.calls = []
        self.leaks = []
        self.denied = set()
        self.minted = 0

    def __call__(self, method, url, headers, body):
        parts = urlsplit(url)
        lowered = {name.lower(): value for name, value in headers.items()}
        wire = " ".join([url, body.decode(), *map(str, headers.values())])
        if self.credentials["secret_access_key"] in wire:
            self.leaks.append(url)
        match = AUTHORIZATION.match(lowered.get("authorization", ""))
        if not match or match["key"] != self.credentials["access_key_id"]:
            return _error(403, "InvalidClientTokenId", IAM_NS)
        names = match["signed"].split(";")
        expected = aws_api.sign(
            method,
            parts.netloc,
            parts.path,
            query=dict(parse_qsl(parts.query, keep_blank_values=True)),
            headers={n: lowered[n] for n in names if n not in ("host", "x-amz-date")},
            body=body,
            api={"region": match["region"], "service": match["service"]},
            credentials=self.credentials,
            amz_date=lowered["x-amz-date"],
        )
        if expected["Authorization"] != lowered["authorization"]:
            return _error(403, "SignatureDoesNotMatch", IAM_NS)
        if parts.netloc == IAM_HOST and method == "POST":
            return self._iam(dict(parse_qsl(body.decode())))
        if parts.netloc == ROUTE53_HOST and method == "GET":
            return self._route53(parts.path, dict(parse_qsl(parts.query)))
        return _error(404, "UnknownOperation", IAM_NS)

    def writes(self):
        return [c for c in self.calls if not c.startswith(("Get", "List"))]

    def _iam(self, params):
        action = params["Action"]
        self.calls.append(action)
        if params.get("Version") != aws_api.IAM_VERSION:
            return _error(400, "InvalidParameterValue", IAM_NS)
        if action in self.denied:
            return _error(403, "AccessDenied", IAM_NS)
        name = params["UserName"]
        user = self.users.get(name)
        if action == "CreateUser":
            if user is not None:
                return _error(409, "EntityAlreadyExists", IAM_NS)
            self.users[name] = {"policies": {}, "keys": {}, "attached": False}
            return self._ok(action, f"<User><UserName>{name}</UserName></User>")
        if user is None:
            return _error(404, "NoSuchEntity", IAM_NS)
        handler = getattr(self, f"_{CAMEL.sub('_', action).lower()}")
        return handler(action, name, user, params)

    def _ok(self, action, inner):
        result = f"<{action}Result>{inner}</{action}Result>" if inner else ""
        metadata = "<ResponseMetadata><RequestId>r</RequestId></ResponseMetadata>"
        return 200, _xml(f"{action}Response", f"{result}{metadata}", IAM_NS)

    def _page(self, action, field, values, params):
        start = int(params.get("Marker", "0"))
        page = values[start : start + PAGE]
        truncated = start + PAGE < len(values)
        marker = f"<Marker>{start + PAGE}</Marker>" if truncated else ""
        inner = (
            f"<{field}>{''.join(f'<member>{v}</member>' for v in page)}</{field}>"
            f"<IsTruncated>{str(truncated).lower()}</IsTruncated>{marker}"
        )
        return self._ok(action, inner)

    def _get_user(self, action, name, user, params):
        arn = f"arn:aws:iam::123456789012:user/{name}"
        return self._ok(
            action, f"<User><UserName>{name}</UserName><Arn>{arn}</Arn></User>"
        )

    def _list_user_policies(self, action, name, user, params):
        return self._page(action, "PolicyNames", sorted(user["policies"]), params)

    def _get_user_policy(self, action, name, user, params):
        document = user["policies"].get(params["PolicyName"])
        if document is None:
            return _error(404, "NoSuchEntity", IAM_NS)
        inner = (
            f"<UserName>{name}</UserName><PolicyName>{params['PolicyName']}</PolicyName>"
            f"<PolicyDocument>{quote(document)}</PolicyDocument>"
        )
        return self._ok(action, inner)

    def _put_user_policy(self, action, name, user, params):
        json.loads(params["PolicyDocument"])
        user["policies"][params["PolicyName"]] = params["PolicyDocument"]
        return self._ok(action, "")

    def _delete_user_policy(self, action, name, user, params):
        if user["policies"].pop(params["PolicyName"], None) is None:
            return _error(404, "NoSuchEntity", IAM_NS)
        return self._ok(action, "")

    def _list_access_keys(self, action, name, user, params):
        members = [
            f"<UserName>{name}</UserName><AccessKeyId>{key}</AccessKeyId>"
            f"<Status>{status}</Status><CreateDate>2026-11-14T00:00:00Z</CreateDate>"
            for key, status in user["keys"].items()
        ]
        return self._page(action, "AccessKeyMetadata", members, params)

    def _create_access_key(self, action, name, user, params):
        if len(user["keys"]) >= KEY_LIMIT:
            return _error(409, "LimitExceeded", IAM_NS)
        self.minted += 1
        key = f"AKIAWORKSPACE{self.minted:07d}"
        user["keys"][key] = "Active"
        inner = (
            f"<AccessKey><UserName>{name}</UserName><AccessKeyId>{key}</AccessKeyId>"
            f"<Status>Active</Status><SecretAccessKey>minted-secret-{self.minted}"
            f"</SecretAccessKey></AccessKey>"
        )
        return self._ok(action, inner)

    def _delete_access_key(self, action, name, user, params):
        if user["keys"].pop(params["AccessKeyId"], None) is None:
            return _error(404, "NoSuchEntity", IAM_NS)
        return self._ok(action, "")

    def _delete_user(self, action, name, user, params):
        if user["keys"] or user["policies"] or user["attached"]:
            return _error(409, "DeleteConflict", IAM_NS)
        del self.users[name]
        return self._ok(action, "")

    def _route53(self, path, query):
        self.calls.append("ListHostedZonesByName")
        if path != "/2013-04-01/hostedzonesbyname":
            return _error(404, "UnknownOperation", ROUTE53_NS)
        if "ListHostedZonesByName" in self.denied:
            return _error(403, "AccessDenied", ROUTE53_NS)
        start = _labels(query["dnsname"])
        listed = sorted(
            (z for z in self.zones if _labels(z[1]) >= start),
            key=lambda z: _labels(z[1]),
        )[: int(query["maxitems"])]
        zones = "".join(
            f"<HostedZone><Id>/hostedzone/{zone_id}</Id><Name>{name}</Name>"
            f"<CallerReference>c</CallerReference><Config><PrivateZone>false"
            f"</PrivateZone></Config><ResourceRecordSetCount>2</ResourceRecordSetCount>"
            f"</HostedZone>"
            for zone_id, name in listed
        )
        inner = (
            f"<HostedZones>{zones}</HostedZones><DNSName>{query['dnsname']}</DNSName>"
            f"<IsTruncated>false</IsTruncated><MaxItems>{query['maxitems']}</MaxItems>"
        )
        return 200, _xml("ListHostedZonesByNameResponse", inner, ROUTE53_NS)
