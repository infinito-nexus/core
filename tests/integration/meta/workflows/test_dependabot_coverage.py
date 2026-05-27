import fnmatch
import subprocess
import unittest
from collections.abc import Iterable
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

DEPENDABOT_PATH = PROJECT_ROOT / ".github" / "dependabot.yml"

# Directories skipped when walking the repository
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".tox",
    "build",
    "dist",
}

# Hidden directories that may contain real dependency manifests
SCANNED_HIDDEN_DIRS = {
    ".github",
    ".devcontainer",
}

# File suffixes that indicate generated/template files, not real dependency files
SKIP_SUFFIXES = (".j2",)

GITIGNORE_PATH = PROJECT_ROOT / ".gitignore"

# Mapping: Dependabot ecosystem name → indicator filename patterns (fnmatch-style)
ECOSYSTEM_FILENAME_INDICATORS: dict[str, list[str]] = {
    "pip": [
        "pyproject.toml",
        "requirements.txt",
        "requirements*.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
    ],
    "uv": ["uv.lock"],
    "npm": ["package.json"],
    "bun": ["bun.lockb"],
    "cargo": ["Cargo.toml"],
    "rust-toolchain": ["rust-toolchain.toml", "rust-toolchain"],
    "composer": ["composer.json"],
    "gomod": ["go.mod"],
    "maven": ["pom.xml"],
    "gradle": ["build.gradle", "build.gradle.kts"],
    "nuget": ["*.csproj", "*.fsproj", "*.vbproj"],
    "dotnet-sdk": ["global.json"],
    "mix": ["mix.exs"],
    "swift": ["Package.swift"],
    "pub": ["pubspec.yaml"],
    "conda": ["environment.yml"],
    "julia": ["Project.toml", "JuliaProject.toml"],
    "elm": ["elm.json"],
    "bazel": ["MODULE.bazel", "WORKSPACE", "WORKSPACE.bazel"],
    "vcpkg": ["vcpkg.json"],
    "gitsubmodule": [".gitmodules"],
    "bundler": ["Gemfile", "gems.rb"],
    "terraform": ["*.tf"],
    "opentofu": ["*.tf"],
    "helm": ["Chart.yaml"],
    "pre-commit": [".pre-commit-config.yaml"],
    "docker": ["Dockerfile", "*.dockerfile", "Dockerfile.*"],
    "docker-compose": [
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ],
}

# Mapping: Dependabot ecosystem name → repository-relative path patterns
ECOSYSTEM_PATH_INDICATORS: dict[str, list[str]] = {
    "github-actions": [
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        "action.yml",
        "action.yaml",
    ],
    "devcontainers": [
        ".devcontainer/devcontainer.json",
        ".devcontainer/*/devcontainer.json",
    ],
}

# Ecosystem groups where any one active member covers the shared file type.
# E.g. terraform and opentofu both consume *.tf — either being active is sufficient.
EQUIVALENT_ECOSYSTEMS: list[frozenset[str]] = [
    frozenset({"terraform", "opentofu"}),
]


def _dir_covers(dep_dir: str, file_rel_dir: str) -> bool:
    """Return True if a Dependabot directory pattern covers a file's relative directory.

    dep_dir is as written in dependabot.yml (e.g. '/', '/**', '/roles/foo/').
    file_rel_dir is the directory of the file relative to PROJECT_ROOT (e.g. 'roles/foo').
    An empty file_rel_dir means the file is at the repo root.

    For many ecosystems GitHub's Dependabot treats '/' as "search recursively
    from root", which means it covers all sub-directories too.
    """
    norm_dep = "/" + dep_dir.strip("/") if dep_dir.strip("/") else "/"
    norm_file = "/" + file_rel_dir.strip("/") if file_rel_dir else "/"

    # '/' and '/**' are both "cover the entire repository"
    if norm_dep in ("/", "/**"):
        return True

    return norm_file == norm_dep or norm_file.startswith(norm_dep + "/")


def _load_active_entries() -> list[dict]:
    data = load_yaml_any(str(DEPENDABOT_PATH)) or {}
    return data.get("updates", [])


def _get_entry_dirs(entry: dict) -> list[str]:
    if "directories" in entry:
        return entry["directories"]
    return [entry.get("directory", "/")]


def _matching_ecosystems(rel_file: str, filename: str) -> set[str]:
    matched = {
        ecosystem
        for ecosystem, patterns in ECOSYSTEM_FILENAME_INDICATORS.items()
        if any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)
    }
    matched.update(
        ecosystem
        for ecosystem, patterns in ECOSYSTEM_PATH_INDICATORS.items()
        if any(fnmatch.fnmatch(rel_file, pattern) for pattern in patterns)
    )
    return matched


def _list_candidate_files() -> Iterable[str]:
    """Yield repo-relative file paths to inspect for ecosystem coverage.

    Prefers `git ls-files` (only tracked files, matches Dependabot's view of
    the repo). Falls back to os.walk with an explicit untracked-skip list when
    git is unavailable or PROJECT_ROOT is not a git checkout (e.g. inside the
    test-integration container where /opt/src/infinito is a bind mount of the
    source tree without .git/).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "ls-files", "-z"],
            check=True,
            capture_output=True,
        )
        return [p for p in result.stdout.decode().split("\0") if p]
    except (FileNotFoundError, subprocess.CalledProcessError):
        return _walk_fallback()


def _load_gitignore_patterns() -> list[str]:
    """Return non-comment, non-blank, non-negated lines from the repo .gitignore.

    The fallback walker uses these as fnmatch patterns to mimic git's view of
    which files are tracked. We deliberately ignore negation (`!`) — the repo
    .gitignore contains none, and supporting it would require a real
    pathspec implementation.
    """
    if not GITIGNORE_PATH.is_file():
        return []
    patterns: list[str] = []
    for raw in read_text(str(GITIGNORE_PATH)).splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        patterns.append(line.rstrip("/"))
    return patterns


def _is_gitignored(rel_file: str, filename: str, patterns: Iterable[str]) -> bool:
    """Best-effort fnmatch-based check that mirrors a tracked-file filter.

    A pattern matches if it equals (or fnmatch-matches) either the basename or
    the repo-relative path. Sufficient for the simple patterns this repo ships
    in .gitignore (filenames, `*.ext` globs, and short directory names).
    """
    for pattern in patterns:
        if fnmatch.fnmatch(filename, pattern) or fnmatch.fnmatch(rel_file, pattern):
            return True
    return False


def _walk_fallback() -> list[str]:
    """Project-tree walk that mirrors git's tracked-file view.

    Routes through :func:`utils.cache.files.iter_non_ignored_files`, which
    composes the cached project walk with the canonical gitignore matcher,
    then layers the SKIP_DIRS / hidden-dir filters this test still needs
    (``iter_non_ignored_files`` does not strip ``.git``-style metadata
    directories on its own).
    """
    files: list[str] = []
    for abs_path in iter_non_ignored_files():
        try:
            rel_path = Path(abs_path).relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        parts = rel_path.parts
        skip = False
        for i, part in enumerate(parts):
            if part in SKIP_DIRS:
                skip = True
                break
            if (
                part.startswith(".")
                and part not in SCANNED_HIDDEN_DIRS
                and i < len(parts) - 1
            ):
                skip = True
                break
        if skip:
            continue
        files.append(rel_path.as_posix())
    return files


class TestDependabotCoverage(unittest.TestCase):
    def test_all_dependency_files_are_covered(self):
        """Every dependency file found in the repository must be covered by an
        active Dependabot entry.  The test fails when a new ecosystem file is
        added (e.g. a Gemfile or Cargo.toml inside a role) but the matching
        ecosystem is still commented-out in .github/dependabot.yml."""

        active = _load_active_entries()

        # Build lookup: ecosystem → [directory patterns]
        ecosystem_dirs: dict[str, list[str]] = {}
        for entry in active:
            eco = entry["package-ecosystem"]
            ecosystem_dirs.setdefault(eco, []).extend(_get_entry_dirs(entry))

        uncovered: list[str] = []

        # Only scan files actually tracked by git. Dependabot operates on the
        # committed tree, so untracked working-copy artefacts (stray host config,
        # editor scratch files, etc.) must not influence coverage. Containerised
        # test runs bind-mount the source tree without .git/, so git may be
        # unavailable — fall back to os.walk plus an explicit untracked skip
        # list when that happens.
        candidate_files = _list_candidate_files()

        for rel_file in candidate_files:
            if not rel_file:
                continue

            filename = Path(rel_file).name
            rel_dir = str(Path(rel_file).parent)

            top_segment = rel_file.split("/", 1)[0]
            if top_segment in SKIP_DIRS:
                continue
            if (
                top_segment.startswith(".")
                and top_segment not in SCANNED_HIDDEN_DIRS
                and top_segment != filename
            ):
                continue

            if any(filename.endswith(s) for s in SKIP_SUFFIXES):
                continue

            for ecosystem in sorted(_matching_ecosystems(rel_file, filename)):
                # Collect all ecosystem names that are equivalent for this file
                candidates: set[str] = {ecosystem}
                for group in EQUIVALENT_ECOSYSTEMS:
                    if ecosystem in group:
                        candidates |= group

                covered = any(
                    any(
                        _dir_covers(dep_dir, rel_dir)
                        for dep_dir in ecosystem_dirs.get(eco, [])
                    )
                    for eco in candidates
                )

                if not covered:
                    uncovered.append(f"{rel_file}  →  ecosystem: {ecosystem}")

        if uncovered:
            self.fail(
                "The following dependency files exist but are NOT covered by an active"
                " Dependabot entry in .github/dependabot.yml.\n"
                "Enable the matching ecosystem or add the directory to an existing entry:\n\n"
                + "\n".join(f"  {entry}" for entry in sorted(uncovered))
            )


if __name__ == "__main__":
    unittest.main()
