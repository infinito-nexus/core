"""Probe many URLs from the managed host in one module call.

Args:
    urls: mapping of a name to the URL probed for it.
    method: HTTP method of every request.
    status_codes: statuses that count as an answer; any other is retried.
    attempts: requests per URL before it counts as unanswered.
    delay: seconds between two attempts at one URL.
    timeout: seconds per request.
    validate_certs: whether TLS certificates are verified.
    follow_redirects: how a redirect is handled, as open_url takes it; with
        ``none`` the redirect status itself is the answer.
    workers: requests in flight at once.

Returns:
    status: mapping of every name to its last HTTP status, -1 without a response.
    errors: mapping of every name whose last attempt got no response to the
        error that attempt raised.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import open_url

ARGUMENT_SPEC = {
    "urls": {"type": "dict", "required": True},
    "method": {"type": "str", "required": True},
    "status_codes": {"type": "list", "elements": "int", "required": True},
    "attempts": {"type": "int", "required": True},
    "delay": {"type": "int", "required": True},
    "timeout": {"type": "int", "required": True},
    "validate_certs": {"type": "bool", "required": True},
    "follow_redirects": {
        "type": "str",
        "required": True,
        "choices": ["all", "none", "safe", "urllib2"],
    },
    "workers": {"type": "int", "required": True},
}


def probe(url, params):
    status, error = -1, None
    for attempt in range(params["attempts"]):
        if attempt:
            time.sleep(params["delay"])
        try:
            with open_url(
                url,
                method=params["method"],
                timeout=params["timeout"],
                validate_certs=params["validate_certs"],
                follow_redirects=params["follow_redirects"],
            ) as response:
                status, error = response.status, None
        except HTTPError as answer:
            status, error = answer.code, None
        except (URLError, OSError) as failure:
            status, error = -1, f"{type(failure).__name__}: {failure}"
        if status in params["status_codes"]:
            break
    return status, error


def probe_all(urls, params):
    with ThreadPoolExecutor(max_workers=params["workers"]) as pool:
        futures = {name: pool.submit(probe, url, params) for name, url in urls.items()}
        return {name: future.result() for name, future in futures.items()}


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    results = probe_all(module.params["urls"], module.params)
    status = {name: code for name, (code, _) in results.items()}
    errors = {name: error for name, (_, error) in results.items() if error}
    unanswered = sorted(
        name
        for name, code in status.items()
        if code not in module.params["status_codes"]
    )
    if unanswered:
        module.fail_json(
            msg=f"{len(unanswered)} URL(s) gave no expected status",
            unanswered=unanswered,
            status=status,
            errors=errors,
        )
    module.exit_json(changed=False, status=status, errors=errors)


if __name__ == "__main__":
    main()
