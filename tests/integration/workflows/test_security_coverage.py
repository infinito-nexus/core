import fnmatch
import os
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files

REPO_ROOT = Path(__file__).resolve().parents[3]
SECURITY_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "security-codeql.yml"

# Hidden directories that are the only ones worth scanning (the cached walker
# already prunes .git/.venv/__pycache__/node_modules etc.).
SCANNED_HIDDEN_DIRS = {
    ".github",
}

# Mapping: CodeQL language name -> filename patterns
CODEQL_FILENAME_INDICATORS: dict[str, list[str]] = {
    "c-cpp": ["*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx"],
    "csharp": ["*.cs"],
    "go": ["*.go"],
    "java-kotlin": ["*.java", "*.kt", "*.kts"],
    "javascript-typescript": ["*.js", "*.jsx", "*.ts", "*.tsx", "*.mjs", "*.cjs"],
    "python": ["*.py"],
    "ruby": ["*.rb"],
    "rust": ["*.rs"],
    "swift": ["*.swift"],
}

# Mapping: CodeQL language name -> repository-relative path patterns
CODEQL_PATH_INDICATORS: dict[str, list[str]] = {
    "actions": [
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        "action.yml",
        "action.yaml",
    ],
}


def _load_active_languages() -> set[str]:
    with open(SECURITY_WORKFLOW_PATH) as fh:
        data = yaml.safe_load(fh)

    include = data["jobs"]["analyze"]["strategy"]["matrix"]["include"]
    return {
        entry["language"]
        for entry in include
        if isinstance(entry, dict) and "language" in entry
    }


def _matching_languages(rel_file: str, filename: str) -> set[str]:
    matched = {
        language
        for language, patterns in CODEQL_FILENAME_INDICATORS.items()
        if any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)
    }
    matched.update(
        language
        for language, patterns in CODEQL_PATH_INDICATORS.items()
        if any(fnmatch.fnmatch(rel_file, pattern) for pattern in patterns)
    )
    return matched


class TestSecurityWorkflowCoverage(unittest.TestCase):
    def test_codeql_languages_match_repository_content(self):
        """The CodeQL workflow must only enable languages that are actually
        present in the repository, and it must not miss any detected language."""

        detected_languages: set[str] = set()

        for path in iter_project_files():
            rel_file = os.path.relpath(path, REPO_ROOT)
            # Skip top-level hidden directories that are not SCANNED_HIDDEN_DIRS
            # (the cached walker already prunes the vendor/cache junk).
            top = rel_file.split(os.sep, 1)[0]
            if top.startswith(".") and top not in SCANNED_HIDDEN_DIRS:
                continue
            filename = os.path.basename(rel_file)
            detected_languages.update(_matching_languages(rel_file, filename))

        active_languages = _load_active_languages()
        missing_languages = sorted(detected_languages - active_languages)
        extra_languages = sorted(active_languages - detected_languages)

        problems: list[str] = []
        if missing_languages:
            problems.append(
                "Detected languages missing from .github/workflows/security-codeql.yml:"
            )
            problems.extend(f"  - {language}" for language in missing_languages)

        if extra_languages:
            problems.append(
                "Active CodeQL languages without matching repository files:"
            )
            problems.extend(f"  - {language}" for language in extra_languages)

        if problems:
            self.fail(
                "The CodeQL workflow matrix does not match the repository content.\n"
                "Enable missing languages or comment out inactive ones.\n\n"
                + "\n".join(problems)
            )


if __name__ == "__main__":
    unittest.main()
