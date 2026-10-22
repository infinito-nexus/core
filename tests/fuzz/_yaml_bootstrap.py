import sys

import atheris

from utils.cache.yaml import load_yaml_str

with atheris.instrument_imports():
    from utils.yaml_bootstrap import BootstrapYamlError, load_block


def fuzz_one_input(data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    try:
        parsed = load_block(text)
    except BootstrapYamlError:
        return
    assert parsed == load_yaml_str(text), text


if __name__ == "__main__":
    atheris.Setup(sys.argv, fuzz_one_input)
    atheris.Fuzz()
