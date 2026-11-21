from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from utils import PROJECT_ROOT

PERL = shutil.which("perl")
ROLE = PROJECT_ROOT / "roles" / "web-app-proxmox"
SCRIPTS = ROLE / "files" / "perl"

_RECORDER = """package {package};
use strict;
use warnings;
use JSON::PP;
our $AUTOLOAD;
sub AUTOLOAD {{
    my ($class, $param) = @_;
    (my $method = $AUTOLOAD) =~ s/.*:://;
    return if $method eq 'DESTROY';
    open my $fh, '>>', $ENV{{FAKE_PVE_CALLS}} or die "calls: $!";
    print $fh JSON::PP->new->canonical->encode({{ method => "$class->$method", param => $param }}), "\\n";
    close $fh;
    open my $returns, '<', $ENV{{FAKE_PVE_RETURNS}} or die "returns: $!";
    local $/;
    return JSON::PP::decode_json(<$returns>)->{{"$class->$method"}};
}}
1;
"""

_MODULES = {
    "PVE/RPCEnvironment.pm": "package PVE::RPCEnvironment;\nsub setup_default_cli_env { return; }\n1;\n",
    "PVE/AccessControl.pm": "package PVE::AccessControl;\n1;\n",
    "PVE/Cluster.pm": """package PVE::Cluster;
use strict;
use warnings;
use JSON::PP;
use Exporter 'import';
our @EXPORT_OK = qw(cfs_read_file);
sub cfs_read_file {
    my ($name) = @_;
    open my $fh, '<', $ENV{FAKE_PVE_STATE} or die "state: $!";
    local $/;
    return decode_json(<$fh>)->{$name};
}
1;
""",
    **{
        f"PVE/API2/{name}.pm": _RECORDER.format(package=f"PVE::API2::{name}")
        for name in ("Domains", "Group", "ACL", "User", "Role", "Pool")
    },
}


@dataclass
class Run:
    """Outcome of one script run against the fake Proxmox VE.

    Args:
        returncode: exit status of perl.
        stdout: what the script printed.
        stderr: what the script died with.
        calls: every recorded API call as ``{"method": "<class>-><name>", "param": {...}}``.
    """

    returncode: int
    stdout: str
    stderr: str
    calls: list[dict]


def run_script(
    source: str, state: dict, env: dict[str, str], returns: dict | None = None
) -> Run:
    """Run a Perl script with stub PVE modules that serve ``state`` and record calls.

    Args:
        source: the Perl program text.
        state: ``{"domains.cfg": {...}, "user.cfg": {...}}`` served by ``cfs_read_file``.
        env: the script's environment, without PATH.
        returns: what each recorded call answers, keyed by ``"<class>-><name>"``; a call without an entry answers undef.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel, text in _MODULES.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding="utf-8")
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
        (root / "returns.json").write_text(json.dumps(returns or {}), encoding="utf-8")
        calls = root / "calls.jsonl"
        calls.touch()
        result = subprocess.run(
            [PERL, "-I", str(root), "-"],
            input=source,
            text=True,
            capture_output=True,
            check=False,
            env={
                **env,
                "FAKE_PVE_STATE": str(root / "state.json"),
                "FAKE_PVE_CALLS": str(calls),
                "FAKE_PVE_RETURNS": str(root / "returns.json"),
            },
        )
        lines = calls.read_text().splitlines()  # nocheck: cache-read tempdir fixture
        recorded = [json.loads(line) for line in lines]
    return Run(result.returncode, result.stdout, result.stderr, recorded)
