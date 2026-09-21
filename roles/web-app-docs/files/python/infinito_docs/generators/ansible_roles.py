from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_README


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
    return result.stdout.decode("utf-8")


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
            f"**Description:** {galaxy_info.get('description', 'No description available')}",
            "",
            "Variables",
            "---------",
            "",
            *(f"- **{key}**: {value}" for key, value in galaxy_info.items()),
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
