"""`infinito meta cache` subcommand -- render the derived cache files.

The nginx upstream map, the consumer compose override and the package
managers' client configuration all follow from the ``cache:`` declarations
in the roles' `meta/networks.yml`. None of them is tracked; this package
regenerates them. Implementation lives in `utils.cache.render`.

It is deliberately separate from `cli.meta.env`, which has to import on the
bare bootstrap python and therefore cannot reach Jinja or PyYAML.
"""

from utils.cache import PROJECT_ROOT

__all__ = ["PROJECT_ROOT"]
