# Bcrypt hashing via the raw `bcrypt` package, bypassing Ansible's built-in
# `password_hash('bcrypt')` filter.
#
# `password_hash('bcrypt')` routes through passlib, whose bcrypt backend runs
# a self-test (`detect_wrap_bug`) against a fixed known-answer secret on
# first use. In environments where the installed `bcrypt` package and
# passlib's bundled version-detection drift apart (`bcrypt` has no
# `__about__.__version__` attribute passlib expects), that self-test itself
# raises "password cannot be longer than 72 bytes" — a misleading error
# unrelated to the caller's actual input, and one that makes the filter
# unusable for ANY input, not just long ones. The raw `bcrypt` package has no
# such self-test and hashes correctly in the same environment.
from __future__ import annotations

import bcrypt


class FilterModule:
    def filters(self):
        return {
            "bcrypt_hash": self.bcrypt_hash,
        }

    @staticmethod
    def bcrypt_hash(value):
        if not isinstance(value, str) or not value:
            raise ValueError("bcrypt_hash: value must be a non-empty string")

        return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
