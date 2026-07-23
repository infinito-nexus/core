#!/usr/bin/env python3
from utils.get_url import get_url


class FilterModule:
    """Infinito.Nexus application config extraction filters"""

    def filters(self):
        return {
            "get_url": get_url,
        }
