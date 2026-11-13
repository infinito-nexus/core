from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urlparse


class HttpsRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if target.scheme != "https":
            raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target.netloc != urlparse(req.full_url).netloc:
            new.remove_header("Authorization")
        return new


OPENER = urllib.request.build_opener(HttpsRedirectHandler)
