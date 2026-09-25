from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README


SECTION_CHARS = set("=-`:'\"~^_*+#<>")


def _fit_underlines(rst: str) -> str:
    """Return ``rst`` with every section underline at least as long as its title.

    A heading that ends in a stray variation selector or zero-width joiner, left
    behind where an emoji was removed, makes pandoc count one character fewer
    than docutils does, and docutils then reports the underline as too short.

    Args:
        rst: reStructuredText as pandoc produced it.
    """
    lines = rst.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        title = lines[index - 1]
        if not line or not title.strip() or set(line) - SECTION_CHARS:
            continue
        if len(line) < len(title):
            lines[index] = line[0] * len(title)
    return "\n".join(lines) + ("\n" if rst.endswith("\n") else "")


def convert_md_to_rst(md_content):
    try:
        result = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "rst"],
            input=md_content.encode("utf-8"),
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        print("Error converting Markdown to reStructuredText:", exc)
        return md_content
    return _fit_underlines(result.stdout.decode("utf-8"))


INLINE_MARKUP = ("\\", "*", "`", "|", "_")


def _one_line(value) -> str:
    """Return ``value`` as a single reStructuredText line.

    ``galaxy_info.company`` is a block scalar in almost every role, and its
    second line landed in column 0, which ends the bullet list it sits in.
    Metadata is prose, not markup, so a character that opens inline markup is
    escaped rather than left to look for a partner: one description reads
    ``(*.parent)`` and reported an unterminated emphasis.

    Args:
        value: a value read from ``galaxy_info``.
    """
    text = " ".join(str(value).split())
    for character in INLINE_MARKUP:
        text = text.replace(character, f"\\{character}")
    return text


def generate_ansible_roles_doc(roles_dir, output_dir):
    """Write one ``<role>.rst`` per role that has a ``meta/main.yml``.

    Args:
        roles_dir: directory holding one sub-directory per role.
        output_dir: directory the ``.rst`` files are written to.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    for role in Path(roles_dir).iterdir():
        meta_file = role / ROLE_FILE_META_MAIN
        if not meta_file.exists():
            continue
        galaxy_info = load_yaml(str(meta_file)).get("galaxy_info", {})
        lines = [
            f"{role.name.capitalize()} Role",
            "=" * (len(role.name) + 7),
            "",
            "**Description:** "
            + _one_line(galaxy_info.get("description", "No description available")),
            "",
            "Variables",
            "---------",
            "",
            *(
                f"- **{key}**: {_one_line(value)}"
                for key, value in galaxy_info.items()
            ),
        ]
        text = "\n".join(lines) + "\n"

        readme = role / ROLE_FILE_README
        if readme.exists():
            text += "\nREADME\n------\n\n" + convert_md_to_rst(
                readme.read_text(encoding="utf-8")
            )
        (output / f"{role.name}.rst").write_text(text, encoding="utf-8")

    print(f"Ansible roles documentation has been generated in {output_dir}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate documentation for Ansible roles."
    )
    parser.add_argument(
        "--roles-dir", required=True, help="Directory containing Ansible roles."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory where documentation will be saved.",
    )
    args = parser.parse_args(argv)

    generate_ansible_roles_doc(args.roles_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
