"""Client limits the env generator and the translator must agree on.

They live apart from the client itself because the generator runs on the bare
bootstrap interpreter: importing the client would pull in the language table and
with it a YAML parser the generator is not allowed to need.
"""

from __future__ import annotations

BATCH_SIZE = 20
