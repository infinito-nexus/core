from typing import Any

import yaml
from yaml.loader import SafeLoader

from utils.cache.files import read_text
from utils.handler.vault import VaultScalar


class YamlHandler:
    @staticmethod
    def load_yaml(path) -> dict:
        """Load the YAML file and wrap existing !vault entries."""
        text = read_text(str(path))
        # Custom Loader subclass wraps !vault scalars; the path-keyed
        # cache cannot preserve that wrapping, so go direct here.
        data = yaml.load(text, Loader=SafeLoader) or {}  # nocheck: direct-yaml
        return YamlHandler.wrap_existing_vaults(data)

    @staticmethod
    def wrap_existing_vaults(node: Any) -> Any:
        """Recursively wrap any str that begins with '$ANSIBLE_VAULT' in a VaultScalar so it dumps as a literal block."""
        if isinstance(node, dict):
            return {k: YamlHandler.wrap_existing_vaults(v) for k, v in node.items()}
        if isinstance(node, list):
            return [YamlHandler.wrap_existing_vaults(v) for v in node]
        if isinstance(node, str) and node.lstrip().startswith("$ANSIBLE_VAULT"):
            return VaultScalar(node)
        return node
