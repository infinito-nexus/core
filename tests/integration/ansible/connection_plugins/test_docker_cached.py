"""The cached docker connection must ask the Docker CLI for its version once per run.

The stock ``community.docker.docker`` connection runs ``docker version`` twice
before every module run once a remote user is set, because every task-host
gets a fresh connection in a fresh worker. ``docker_cached`` keeps the answer
for the run. These cases run the same play through both plugins against a
stand-in ``docker`` executable that logs every call and runs the exec payload
locally: the cached plugin must make the same exec calls with the same
results, and only the first task-host may query the version.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from . import PROJECT_ROOT

SHIM = f"""#!{sys.executable}
import json
import os
import subprocess
import sys

args = sys.argv[1:]
with open(os.environ["DOCKER_SHIM_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\\n")
if args[:1] == ["version"]:
    print("29.1.3" if "--format" in args else "Client:\\n Version: 29.1.3")
    sys.exit(0)
if args[:1] != ["exec"]:
    sys.exit(2)
rest = args[1:]
env = dict(os.environ)
cwd = None
while rest and rest[0].startswith("-"):
    flag = rest.pop(0)
    if flag in ("-u", "-e", "-w"):
        value = rest.pop(0)
        if flag == "-e":
            key, _, val = value.partition("=")
            env[key] = val
        if flag == "-w":
            cwd = value
rest.pop(0)
sys.exit(subprocess.run(rest, env=env, cwd=cwd, check=False).returncode)
"""

PLAY = """---
- name: Run module, copy and template tasks over a docker connection
  hosts: node1
  gather_facts: false
  tasks:
    - name: Run a command
      ansible.builtin.command: echo hello
      register: command_result
      changed_when: false

    - name: Stat the work directory
      ansible.builtin.stat:
        path: "{{ work_dir }}"
      register: stat_result

    - name: Copy a file
      ansible.builtin.copy:
        content: "copied\\n"
        dest: "{{ work_dir }}/copied.txt"
        mode: "0644"
      register: copy_result

    - name: Template a file
      ansible.builtin.template:
        src: "{{ template_src }}"
        dest: "{{ work_dir }}/templated.txt"
        mode: "0644"
      register: template_result

    - name: Report the results
      ansible.builtin.copy:
        dest: "{{ report }}"
        content: "{{ {'command': command_result.stdout, 'stat': stat_result.stat.isdir, 'copy': copy_result.changed, 'template': template_result.changed} | to_json }}"
        mode: "0644"
      delegate_to: localhost
"""


def _run(workdir: Path, connection: str) -> tuple[dict, list[list[str]], Path]:
    """Run the play once through *connection*.

    Args:
        workdir: an empty directory for the shim, the play and its outputs.
        connection: the ``ansible_connection`` of the node.

    Returns:
        ``(reported results, logged docker calls, work directory of the node)``.

    Raises:
        RuntimeError: when ansible-playbook exits non-zero.
    """
    shim_dir = workdir / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "docker"
    shim.write_text(SHIM, encoding="utf-8")
    shim.chmod(0o755)
    node_dir = workdir / "node"
    node_dir.mkdir()
    template = workdir / "template.j2"
    template.write_text("templated {{ inventory_hostname }}\n", encoding="utf-8")
    (workdir / "play.yml").write_text(PLAY, encoding="utf-8")
    (workdir / "inventory.yml").write_text(
        json.dumps(
            {
                "all": {
                    "hosts": {
                        "node1": {
                            "ansible_connection": connection,
                            "ansible_user": "root",
                            "ansible_python_interpreter": sys.executable,
                            "ansible_remote_tmp": str(workdir / "remote-tmp"),
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    log = workdir / "docker-calls.log"
    report = workdir / "report.json"
    env = os.environ.copy()
    env.update(
        ANSIBLE_CONFIG=str(PROJECT_ROOT / "ansible.cfg"),
        ANSIBLE_LOCAL_TEMP=str(workdir / "ansible-local"),
        DOCKER_SHIM_LOG=str(log),
        PATH=os.pathsep.join([str(shim_dir), env["PATH"]]),
    )
    result = subprocess.run(
        [
            "ansible-playbook",
            "-i",
            str(workdir / "inventory.yml"),
            str(workdir / "play.yml"),
            "-e",
            f"work_dir={node_dir}",
            "-e",
            f"template_src={template}",
            "-e",
            f"report={report}",
        ],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ansible-playbook failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    calls = [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line
    ]
    return json.loads(report.read_text(encoding="utf-8")), calls, node_dir


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook not found")
class TestDockerCachedConnection(unittest.TestCase):
    runs: ClassVar[dict[str, tuple[dict, list[list[str]], dict[str, str]]]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        for connection in ("community.docker.docker", "docker_cached"):
            with tempfile.TemporaryDirectory() as tmp:
                report, calls, node_dir = _run(Path(tmp), connection)
                files = {
                    name: (node_dir / name).read_text(encoding="utf-8")
                    for name in ("copied.txt", "templated.txt")
                }
            cls.runs[connection] = (report, calls, files)

    @staticmethod
    def _kinds(calls: list[list[str]], kind: str) -> list[list[str]]:
        return [call for call in calls if call[:1] == [kind]]

    def test_the_stock_plugin_queries_the_version_before_every_module_run(self):
        _, calls, _ = self.runs["community.docker.docker"]
        self.assertEqual(
            len(self._kinds(calls, "version")),
            8,
            "the stand-in must reproduce the two version calls per task-host, "
            "or the case below proves nothing",
        )

    def test_only_the_first_task_host_queries_the_version(self):
        _, calls, _ = self.runs["docker_cached"]
        self.assertEqual(len(self._kinds(calls, "version")), 2)
        self.assertEqual(calls[0][:1], ["version"])

    def test_the_exec_calls_and_results_match_the_stock_plugin(self):
        stock_report, stock_calls, stock_files = self.runs["community.docker.docker"]
        report, calls, files = self.runs["docker_cached"]
        self.assertEqual(
            len(self._kinds(calls, "exec")), len(self._kinds(stock_calls, "exec"))
        )
        self.assertEqual(report, stock_report)
        self.assertEqual(
            report,
            {"command": "hello", "stat": True, "copy": True, "template": True},
        )
        self.assertEqual(files, stock_files)
        self.assertEqual(files["templated.txt"], "templated node1\n")


if __name__ == "__main__":
    unittest.main()
