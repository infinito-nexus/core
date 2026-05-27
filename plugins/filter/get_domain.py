#!/usr/bin/env python3
from utils.domains.primary_domain import get_domain


class FilterModule:
    def filters(self):
        return {"get_domain": get_domain}
