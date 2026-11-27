from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar, trust_as_template

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.design.cosmos import SERVICE_KEY
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
)
from utils.roles.applications.topics import provider_of
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

RULE = "cosmos-sheets"
ROLES = PROJECT_ROOT / "roles"
SHEET = Path("templates") / "cosmos.css.j2"
VARS = ROLES / "sys-front-inj-design" / ROLE_FILE_VARS_MAIN
ATTRIBUTE = re.compile(r"data-cosmos-(?:mode|legible)")
PLAYWRIGHT = ("files", "playwright")
PLAYWRIGHT_RUNNER = "test-e2e-playwright"
SURFACE = frozenset({"background", "background-color"})
CLEAR = frozenset({"transparent", "none"})
COSMOS_TEXT = "var(--cosmos-text)"
DESIGN_SURFACE = re.compile(r"var\(\s*--design-surface-")
PAGE = frozenset({"html", "body"})
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
COMBINATORS = frozenset(">+~")
TYPE = re.compile(r"[A-Za-z][\w-]*")


def selectors(vars_file: Path = VARS) -> tuple[str, str]:
    """
    Args:
        vars_file: the vars file of ``sys-front-inj-design``.

    Returns:
        ``(sky, legible_top)``: the rendered ``COSMOS_SKY_SELECTOR`` and
        ``COSMOS_LEGIBLE_TOP_SELECTOR``.
    """
    variables = DataLoader().load_from_file(str(vars_file), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables=variables)
    return (
        templar.template(variables["COSMOS_SKY_SELECTOR"]),
        templar.template(variables["COSMOS_LEGIBLE_TOP_SELECTOR"]),
    )


def render(text: str, sky: str, top: str) -> str:
    """
    Args:
        text: the cosmos sheet template.
        sky: the rendered ``COSMOS_SKY_SELECTOR``.
        top: the rendered ``COSMOS_LEGIBLE_TOP_SELECTOR``.

    Returns:
        The sheet as the design injection renders it. A sheet that reads a
        variable beyond the two selectors fails with ``AnsibleError``.
    """
    variables = {"COSMOS_SKY_SELECTOR": sky, "COSMOS_LEGIBLE_TOP_SELECTOR": top}
    return Templar(loader=DataLoader(), variables=variables).template(
        trust_as_template(text)
    )


def _top_level_split(text: str, separator: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(text):
        depth += (char in "([") - (char in ")]")
        if char == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def _declarations(body: str) -> dict[str, str]:
    found = {}
    for declaration in _top_level_split(body, ";"):
        name, _, value = declaration.partition(":")
        found[name.strip().lower()] = value.replace("!important", "").strip().lower()
    return found


def rules(css: str) -> list[tuple[list[str], dict[str, str]]]:
    """
    Args:
        css: a stylesheet.

    Returns:
        ``(selectors, declarations)`` of every style rule, also those inside
        at-rule blocks.
    """
    css = COMMENT.sub("", css)
    found, cursor = [], 0
    while (opening := css.find("{", cursor)) >= 0:
        depth, end = 1, opening + 1
        while depth and end < len(css):
            depth += (css[end] == "{") - (css[end] == "}")
            end += 1
        prelude, body = css[cursor:opening].strip(), css[opening + 1 : end - 1]
        if prelude.startswith("@"):
            found.extend(rules(body))
        else:
            found.append((_top_level_split(prelude, ","), _declarations(body)))
        cursor = end
    return found


def _subject(selector: str) -> str:
    compounds, depth, current = [], 0, ""
    for char in selector:
        depth += (char in "([") - (char in ")]")
        if depth == 0 and (char.isspace() or char in COMBINATORS):
            compounds.append(current)
            current = ""
        else:
            current += char
    compounds = [compound for compound in [*compounds, current] if compound]
    if not compounds:
        return "html"
    match = TYPE.match(compounds[-1])
    return match.group(0).lower() if match else ""


def sheet_findings(name: str, css: str, sky: str, top: str) -> list[str]:
    """
    Args:
        name: the label of the sheet in the findings.
        css: the rendered sheet.
        sky: the rendered ``COSMOS_SKY_SELECTOR``.
        top: the rendered ``COSMOS_LEGIBLE_TOP_SELECTOR``.

    Returns:
        One line per rule of the sheet that breaks the cosmos contract.
    """
    found: list[str] = []
    parsed = rules(css)
    if not parsed:
        found.append(f"{name}: holds no rule")
    clears = glow = False
    for chosen, declared in parsed:
        label = f"{name}: '{', '.join(chosen)}'"
        found.extend(
            f"{label} is not scoped by COSMOS_SKY_SELECTOR"
            for selector in chosen
            if not selector.startswith(sky)
        )
        legible = [selector for selector in chosen if selector.startswith(top)]
        cleared = any(declared.get(prop) in CLEAR for prop in SURFACE)
        clears |= cleared
        if legible:
            glow = True
            found.extend(
                f"{label} gives html or body a surface in the legible-top band"
                for selector in legible
                if _subject(selector[len(top) :]) in PAGE
            )
            if not SURFACE & declared.keys() or cleared or "color" not in declared:
                found.append(
                    f"{label} must give its content blocks a surface and a text color"
                )
        elif cleared and declared.get("color") != COSMOS_TEXT:
            found.append(f"{label} clears a surface without color: {COSMOS_TEXT}")
        elif "color" not in declared and any(
            DESIGN_SURFACE.match(declared.get(prop, "")) for prop in SURFACE
        ):
            found.append(f"{label} paints a design surface without a text color")
    if clears and not glow:
        found.append(f"{name}: clears a surface but has no legible-top rule")
    return found


def project_role_files() -> list[Path]:
    """Returns:
    Every file of the project's roles directory.
    """
    prefix = f"{ROLES}{os.sep}"
    return [Path(path) for path in iter_project_files() if path.startswith(prefix)]


def findings(roles: Path, vars_file: Path, files: list[Path]) -> list[str]:
    """
    Args:
        roles: the roles directory to check.
        vars_file: the vars file that names the cosmos attributes.
        files: every file below ``roles``.

    Returns:
        One line per broken rule of a ``templates/cosmos.css.j2`` and per role
        file that names a cosmos attribute outside ``vars_file``, outside
        the role providing the ``cosmos`` service, which sets them, and
        outside the Playwright runner, whose shared helpers assert them.
    """
    sky, top = selectors(vars_file)
    provider = provider_of(SERVICE_KEY, build_service_registry_from_roles_dir(roles))
    by_role: dict[str, list[Path]] = {}
    for path in files:
        by_role.setdefault(path.relative_to(roles).parts[0], []).append(path)
    lines: list[str] = []
    for role in sorted(path for path in roles.iterdir() if path.is_dir()):
        sheet = role / SHEET
        if sheet.is_file():
            name = f"{role.name}/{SHEET}"
            try:
                css = render(read_text(str(sheet)), sky, top)
            except AnsibleError as error:
                lines.append(
                    f"{name}: renders beyond the two cosmos selectors: {error}"
                )
            else:
                lines.extend(sheet_findings(name, css, sky, top))
        if role.name in (provider, PLAYWRIGHT_RUNNER):
            continue
        for path in sorted(by_role.get(role.name, [])):
            relative = path.relative_to(role).parts
            if relative[:2] == PLAYWRIGHT or path == vars_file:
                continue
            try:
                content = read_text(str(path))
            except UnicodeDecodeError:
                continue
            if ATTRIBUTE.search(content):
                lines.append(
                    f"{path.relative_to(roles)}: names a cosmos attribute; "
                    f"use COSMOS_SKY_SELECTOR or COSMOS_LEGIBLE_TOP_SELECTOR"
                )
    return lines


class TestCosmosSheets(unittest.TestCase):
    def test_every_cosmos_sheet_keeps_the_contract(self) -> None:
        self.assertTrue(
            sorted(ROLES.glob(f"*/{SHEET}")), f"[{RULE}] no {SHEET} under {ROLES}"
        )
        broken = findings(ROLES, VARS, project_role_files())
        self.assertEqual(
            broken,
            [],
            f"[{RULE}] a cosmos sheet scopes every rule by COSMOS_SKY_SELECTOR, "
            f"colors a cleared surface with {COSMOS_TEXT} and gives its content "
            "blocks a surface in the legible-top band while html and body stay "
            "clear:\n  " + "\n  ".join(broken),
        )

    def test_the_rule_flags_each_planted_violation(self) -> None:
        planted = {
            "web-app-unscoped": "body { background: transparent; color: var(--cosmos-text); }\n"
            "{{ COSMOS_LEGIBLE_TOP_SELECTOR }} main { background: var(--design-surface-1); color: var(--design-text); }",
            "web-app-dark-text": "{{ COSMOS_SKY_SELECTOR }} body { background: transparent; color: var(--design-text); }\n"
            "{{ COSMOS_LEGIBLE_TOP_SELECTOR }} main { background: var(--design-surface-1); color: var(--design-text); }",
            "web-app-covered-body": "{{ COSMOS_SKY_SELECTOR }} body { background: transparent; color: var(--cosmos-text); }\n"
            "{{ COSMOS_LEGIBLE_TOP_SELECTOR }} body { background: var(--design-surface-1); color: var(--design-text); }",
            "web-app-no-glow": "{{ COSMOS_SKY_SELECTOR }} body { background: transparent; color: var(--cosmos-text); }",
            "web-app-literal": 'html[data-cosmos-mode="full"] body { background: transparent; color: var(--cosmos-text); }\n'
            "{{ COSMOS_LEGIBLE_TOP_SELECTOR }} main { background: var(--design-surface-1); color: var(--design-text); }",
            "web-app-foreign-variable": "{{ COSMOS_SKY_SELECTOR }} {{ APP_ROOT }} { background: transparent; color: var(--cosmos-text); }",
            "web-app-bare-surface": "{{ COSMOS_SKY_SELECTOR }} body { background: transparent; color: var(--cosmos-text); }\n"
            "{{ COSMOS_SKY_SELECTOR }} .panel { background-color: var(--design-surface-2); }\n"
            "{{ COSMOS_LEGIBLE_TOP_SELECTOR }} main { background: var(--design-surface-1); color: var(--design-text); }",
            "web-app-kept-surface": "{{ COSMOS_SKY_SELECTOR }} body { background: transparent; color: var(--cosmos-text); }\n"
            "{{ COSMOS_SKY_SELECTOR }} .panel { background-color: var(--design-surface-2); color: var(--design-text); }\n"
            "{{ COSMOS_LEGIBLE_TOP_SELECTOR }} main { background: var(--design-surface-1); color: var(--design-text); }",
            "web-app-kept": "{{ COSMOS_SKY_SELECTOR }} body { background: transparent; color: var(--cosmos-text); }\n"
            "@media (min-width: 40rem) { {{ COSMOS_LEGIBLE_TOP_SELECTOR }} body > main { background: var(--design-surface-1); color: var(--design-text); } }",
        }
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            for role, text in planted.items():
                (roles / role / SHEET).parent.mkdir(parents=True)
                (roles / role / SHEET).write_text(text, encoding="utf-8")
            sheets = [roles / role / SHEET for role in planted]
            flagged = {line.split("/", 1)[0] for line in findings(roles, VARS, sheets)}
        self.assertEqual(flagged, set(planted) - {"web-app-kept", "web-app-kept-surface"})

    def test_a_custom_role_is_checked_and_only_the_provider_names_attributes(
        self,
    ) -> None:
        planted = {
            f"web-app-cst-cosmos/{ROLE_FILE_VARS_MAIN}": (
                "application_id: web-app-cst-cosmos\n"
            ),
            f"web-app-cst-cosmos/{ROLE_FILE_META_SERVICES}": (
                f"{SERVICE_KEY}:\n  shared: true\n"
            ),
            "web-app-cst-cosmos/files/javascript/cosmos.js": 'root.setAttribute("data-cosmos-mode", mode);\n',
            "web-app-cst-shop/files/javascript/shop.js": 'document.querySelector("[data-cosmos-mode]");\n',
            f"web-app-cst-shop/{SHEET}": "body { background: transparent; color: var(--cosmos-text); }\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            roles = Path(tmp)
            for name, text in planted.items():
                (roles / name).parent.mkdir(parents=True, exist_ok=True)
                (roles / name).write_text(text, encoding="utf-8")
            broken = findings(roles, VARS, [roles / name for name in planted])
        self.assertEqual(
            sorted({line.split(":", 1)[0] for line in broken}),
            ["web-app-cst-shop/files/javascript/shop.js", f"web-app-cst-shop/{SHEET}"],
        )


if __name__ == "__main__":
    unittest.main()
