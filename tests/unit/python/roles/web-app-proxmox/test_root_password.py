from __future__ import annotations

import re
import unittest

from tests.utils.ansible_assert import assert_task, evaluate, holds, message
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from ._render import DOCKERFILE, ROLE, planted, render

FIRST_BOOT = read_text(str(ROLE / "files" / "shell" / "first-boot.sh"))
VM_FLAVOR = ROLE / "tasks" / "flavors" / "vm.yml"
GUEST_FILE = "flavors/vm/guest.yml"
GUEST_INCLUDE = next(
    task
    for task in load_yaml_any(str(VM_FLAVOR), default_if_missing=[])
    if "ansible.builtin.include_tasks" in task
)
GUEST_TASKS = load_yaml_any(str(ROLE / "tasks" / GUEST_FILE), default_if_missing=[])
GUEST_ANSWERS = "⏳ Wait until the Proxmox VE guest answers on the guest channel"
LOCKED_ASSERT = "🛑 Refuse a Proxmox VE guest whose root password is not locked"
GUEST_LOCK = "pve-guest usermod -L root"
GUEST_STATUS = "pve-guest passwd -S root"
LOCKED = "root L 2026-11-23 0 99999 7 -1"
USABLE = "root P 2026-11-23 0 99999 7 -1"
EMPTY = "root NP 2026-11-23 0 99999 7 -1"
LOCK = "usermod -L root"
PASSWORD_WRITE = re.compile(r"\busermod\b.*\s-[pU]\b|\bchpasswd\b|\bpasswd\b")
DEPLOYED_MEASURE = "\tmeasure deployed\n"
ADMIT_LAUNCHER = ">>/root/.ssh/authorized_keys"
SSHD_DROP_IN = re.compile(
    r"^printf '(?P<config>[^']*)' \\\n\t>/etc/ssh/sshd_config\.d/infinito\.conf$",
    re.MULTILINE,
)
SSHD_SETTINGS = (
    "PasswordAuthentication no",
    "PermitRootLogin prohibit-password",
    "UsePAM yes",
)
IMAGE_LOCK = " && usermod -L root \\"
IMAGE_INSTALL = "install -y --no-install-recommends ${PROXMOX_PACKAGES} systemd-sysv"


def hook_findings(hook: str) -> list[str]:
    """Args:
        hook: text of the first-boot hook.

    Returns:
        Every way the hook leaves root@pam with a usable password, records root
        before the lock, or shuts the launcher's key login out of a locked root.
    """
    lines = hook.splitlines()
    if LOCK not in lines:
        return ["the hook never locks the root password"]
    at = lines.index(LOCK)
    findings = [
        f"{line.strip()!r} writes the root password after the lock"
        for line in lines[at + 1 :]
        if PASSWORD_WRITE.search(line)
    ]
    lock = hook.find(f"\n{LOCK}\n")
    if not lock < hook.find(DEPLOYED_MEASURE):
        findings.append("the record digests root before the lock")
    if not lock < hook.find(ADMIT_LAUNCHER):
        findings.append("the launcher key is admitted before the lock")
    drop_in = SSHD_DROP_IN.search(hook)
    settings = drop_in.group("config").split("\\n") if drop_in else []
    findings.extend(
        f"the sshd drop-in lacks {setting!r}"
        for setting in SSHD_SETTINGS
        if setting not in settings
    )
    return findings


def image_findings(dockerfile: str) -> list[str]:
    """Args:
        dockerfile: the Dockerfile rendered for the container flavor.

    Returns:
        Every way the image leaves root@pam with a password it does not lock.
    """
    lines = dockerfile.splitlines()
    install = next((n for n, line in enumerate(lines) if IMAGE_INSTALL in line), -1)
    if install < 0:
        return ["the image installs no Proxmox VE"]
    if IMAGE_LOCK not in lines[install + 1 :]:
        return ["the image never locks the root password after the install"]
    return [
        f"{line.strip()!r} writes the root password"
        for line in lines
        if PASSWORD_WRITE.search(line)
    ]


def _cmd(task: dict) -> str:
    return str((task.get("ansible.builtin.shell") or {}).get("cmd", ""))


def _lock_task(tasks: list[dict]) -> dict:
    return next(task for task in tasks if GUEST_LOCK in _cmd(task))


def deploy_lock_findings(tasks: list[dict]) -> list[str]:
    """Args:
        tasks: the guest checks of the vm flavor.

    Returns:
        Every way a deploy leaves the root password of an already installed
        guest unlocked or unchecked.
    """
    names = [task.get("name", "") for task in tasks]
    locks = [n for n, task in enumerate(tasks) if GUEST_LOCK in _cmd(task)]
    if not locks:
        return ["no task locks root inside the guest"]
    lock = locks[0]
    reads = [n for n, task in enumerate(tasks) if GUEST_STATUS in _cmd(task)]
    after = [n for n in reads if n > lock]
    findings = []
    if GUEST_ANSWERS not in names or lock < names.index(GUEST_ANSWERS):
        findings.append("root is locked before the guest answers")
    if not any(n < lock for n in reads):
        findings.append("no status read precedes the lock")
    if not after:
        return [*findings, "no status read follows the lock"]
    checked = tasks[after[0]].get("register", "")
    asserts = [
        n
        for n, task in enumerate(tasks)
        if checked and checked in str(task.get("ansible.builtin.assert", {}))
    ]
    if not any(n > after[0] for n in asserts):
        findings.append("no assert checks the status read after the lock")
    return findings


class TestVmGuestRoot(unittest.TestCase):
    def test_the_first_boot_locks_root_and_keeps_the_key_channel(self):
        self.assertEqual(hook_findings(FIRST_BOOT), [])

    def test_negative_control_a_hook_without_the_lock_leaves_root_usable(self):
        mutant = FIRST_BOOT.replace(f"{LOCK}\n", "")
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertEqual(
            hook_findings(mutant), ["the hook never locks the root password"]
        )

    def test_negative_control_a_password_written_after_the_lock_is_caught(self):
        write = 'usermod -p "$root_hash" root\n'
        mutant = FIRST_BOOT.replace(write, "").replace(f"{LOCK}\n", f"{LOCK}\n{write}")
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertEqual(
            hook_findings(mutant),
            [f"{write.strip()!r} writes the root password after the lock"],
        )

    def test_negative_control_an_unlock_after_the_lock_is_caught(self):
        mutant = FIRST_BOOT.replace(f"{LOCK}\n", f"{LOCK}\npasswd -u root\n")
        self.assertIn(
            "'passwd -u root' writes the root password after the lock",
            hook_findings(mutant),
        )

    def test_negative_control_a_lock_after_the_record_is_caught(self):
        mutant = FIRST_BOOT.replace(f"{LOCK}\n", "", 1).replace(
            DEPLOYED_MEASURE, f"{DEPLOYED_MEASURE}{LOCK}\n", 1
        )
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertIn("the record digests root before the lock", hook_findings(mutant))

    def test_negative_control_a_drop_in_without_pam_is_caught(self):
        mutant = FIRST_BOOT.replace("\\nUsePAM yes\\n", "\\n")
        self.assertNotEqual(mutant, FIRST_BOOT)
        self.assertEqual(hook_findings(mutant), ["the sshd drop-in lacks 'UsePAM yes'"])


class TestDeployLock(unittest.TestCase):
    def test_every_deploy_locks_and_checks_root_of_an_installed_guest(self):
        self.assertEqual(deploy_lock_findings(GUEST_TASKS), [])
        self.assertEqual(
            _lock_task(GUEST_TASKS)["delegate_to"], "{{ PROXMOX_HOST_NODE }}"
        )

    def test_negative_control_a_flavor_without_the_lock_is_caught(self):
        tasks = [task for task in GUEST_TASKS if GUEST_LOCK not in _cmd(task)]
        self.assertEqual(len(tasks), len(GUEST_TASKS) - 1)
        self.assertEqual(
            deploy_lock_findings(tasks), ["no task locks root inside the guest"]
        )

    def test_negative_control_a_lock_before_the_guest_answers_is_caught(self):
        lock = _lock_task(GUEST_TASKS)
        tasks = [lock, *(task for task in GUEST_TASKS if task is not lock)]
        self.assertIn(
            "root is locked before the guest answers", deploy_lock_findings(tasks)
        )

    def test_negative_control_a_flavor_without_the_check_is_caught(self):
        tasks = [task for task in GUEST_TASKS if task.get("name") != LOCKED_ASSERT]
        self.assertEqual(len(tasks), len(GUEST_TASKS) - 1)
        self.assertEqual(
            deploy_lock_findings(tasks),
            ["no assert checks the status read after the lock"],
        )

    def test_the_lock_runs_only_while_root_keeps_a_usable_password(self):
        when = _lock_task(GUEST_TASKS)["when"]
        for stdout, runs in ((USABLE, True), (EMPTY, True), (LOCKED, False)):
            scope = {"proxmox_guest_root_status": {"stdout": stdout}}
            self.assertIs(bool(evaluate(when, scope)), runs, stdout)

    def test_the_lock_skips_a_node_that_does_not_host_the_stack(self):
        self.assertEqual(GUEST_INCLUDE["ansible.builtin.include_tasks"], GUEST_FILE)
        when = GUEST_INCLUDE["when"]
        self.assertIs(bool(evaluate(when, {"IS_STACK_HOST": False})), False)
        self.assertIs(bool(evaluate(when, {"IS_STACK_HOST": True})), True)

    def test_the_deploy_refuses_a_guest_whose_root_stays_unlocked(self):
        check = assert_task(ROLE / "tasks" / GUEST_FILE, LOCKED_ASSERT)
        self.assertTrue(holds(check, {"proxmox_guest_root_locked": {"stdout": LOCKED}}))
        for stdout in (USABLE, EMPTY, ""):
            scope = {
                "application_id": "web-app-proxmox",
                "proxmox_guest_root_locked": {"stdout": stdout},
            }
            self.assertFalse(holds(check, scope), stdout)
            self.assertIn(stdout, message(check, scope))


class TestContainerRoot(unittest.TestCase):
    def test_the_container_image_locks_root(self):
        self.assertEqual(image_findings(render(DOCKERFILE, "container")), [])

    def test_negative_control_an_image_without_the_lock_is_caught(self):
        mutant = planted(DOCKERFILE, f"{IMAGE_LOCK}\n", "")
        self.assertEqual(
            image_findings(render(mutant, "container")),
            ["the image never locks the root password after the install"],
        )


if __name__ == "__main__":
    unittest.main()
