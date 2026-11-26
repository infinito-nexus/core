from __future__ import annotations

import functools
import importlib.util
import inspect
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar, cast

from utils.cache.files import PROJECT_ROOT

if TYPE_CHECKING:
    import unittest

NOBODY = 65534
PYTEST_OPTIONS = (
    "-q",
    "-rs",
    "-p",
    "no:cacheprovider",
    "--import-mode=importlib",
    "-o",
    "consider_namespace_packages=true",
    "-o",
    "python_functions=",
)
_OUTCOME = re.compile(r"\b1 (passed|skipped)\b")
_SKIP_REASON = re.compile(r"^SKIPPED \[\d+\] [^\n]*?:\d+: (.*)$", re.MULTILINE)

_Decorated = TypeVar("_Decorated", bound=Callable[..., Any])


def unprivileged_ids() -> tuple[int, int]:
    """
    Returns:
        The checkout owner, which can read the checkout the child imports
        from; ``nobody`` when root owns the checkout.
    """
    owner = PROJECT_ROOT.stat()
    if owner.st_uid == 0:
        return NOBODY, NOBODY
    return owner.st_uid, owner.st_gid


def node_id(test: unittest.TestCase, method: Callable[..., Any]) -> str:
    """
    Args:
        test: the running test case.
        method: the undecorated test method.

    Returns:
        ``<file>::<Class>::<method>``.
    """
    module = sys.modules.get(type(test).__module__)
    path = (
        getattr(module, "__file__", None) or inspect.unwrap(method).__code__.co_filename
    )
    cls = type(test).__qualname__.replace(".", "::")
    return f"{path}::{cls}::{method.__name__}"


def run_dropped(node: str, uid: int, gid: int) -> subprocess.CompletedProcess[str]:
    """
    Args:
        node: the pytest node id.
        uid: user the child runs as.
        gid: group the child runs as, with no supplementary groups.

    Returns:
        The finished child.
    """
    scratch = tempfile.mkdtemp(prefix="infinito-unprivileged-")
    try:
        os.chown(scratch, uid, gid)
        env = {
            **os.environ,
            "HOME": scratch,
            "TMPDIR": scratch,
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                node,
                "--rootdir",
                str(PROJECT_ROOT),
                *PYTEST_OPTIONS,
            ],
            cwd=PROJECT_ROOT,
            env=env,
            user=uid,
            group=gid,
            extra_groups=[],
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def report(
    test: unittest.TestCase, child: subprocess.CompletedProcess[str], uid: int
) -> None:
    """
    Args:
        test: the running test case.
        child: the finished pytest child.
        uid: the uid the child ran as.

    Raises:
        unittest.SkipTest: the child skipped the test.
        AssertionError: the child failed, errored or ran no test.
    """
    output = child.stdout + child.stderr
    outcome = _OUTCOME.search(child.stdout)
    if child.returncode == 0 and outcome and outcome.group(1) == "passed":
        return
    if child.returncode == 0 and outcome and outcome.group(1) == "skipped":
        reason = _SKIP_REASON.search(child.stdout)
        test.skipTest(f"as uid {uid}: {reason.group(1) if reason else output}")
    test.fail(f"the test failed as uid {uid} (exit {child.returncode}):\n{output}")


def unprivileged(test: _Decorated) -> _Decorated:
    """
    Args:
        test: a test method, or a ``unittest.TestCase`` subclass.

    Returns:
        The wrapped method, or the class with each of its own ``test*``
        methods wrapped.
    """
    if isinstance(test, type):
        for name, member in list(vars(test).items()):
            if name.startswith("test") and callable(member):
                setattr(test, name, unprivileged(member))
        return test

    @functools.wraps(test)
    def wrapper(case: unittest.TestCase, *args: Any, **kwargs: Any) -> Any:
        if os.geteuid() != 0:
            return test(case, *args, **kwargs)
        if importlib.util.find_spec("pytest") is None:
            case.skipTest("dropping root needs pytest to select the single test")
        uid, gid = unprivileged_ids()
        report(case, run_dropped(node_id(case, test), uid, gid), uid)
        return None

    return cast("_Decorated", wrapper)


__all__ = [
    "NOBODY",
    "PYTEST_OPTIONS",
    "node_id",
    "report",
    "run_dropped",
    "unprivileged",
    "unprivileged_ids",
]
