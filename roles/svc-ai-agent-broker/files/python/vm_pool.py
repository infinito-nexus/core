from __future__ import annotations

from dataclasses import dataclass, field

TASK_KINDS = ("routine_run", "work_package")


class LeaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class Task:
    """One unit of agent work a VM serves.

    Args:
        kind: ``routine_run`` for one orchestrator routine run,
            ``work_package`` for one claimed work package.
        ref: the run id or the work package id.
    """

    kind: str
    ref: str

    def __post_init__(self):
        if self.kind not in TASK_KINDS:
            raise LeaseError(f"task kind '{self.kind}' is not one of {TASK_KINDS}")
        if not self.ref:
            raise LeaseError("a task needs the id of its run or work package")


@dataclass(frozen=True)
class Lease:
    """The claim of one task on one VM.

    Args:
        vm: the VM name on the hypervisor.
        task: the task the VM serves.
        instance: the Infinito.Nexus instance the broker belongs to.
        broker: the broker process that holds the lease.
        expiry: epoch seconds after which the lease is dead.
    """

    vm: str
    task: Task
    instance: str
    broker: str
    expiry: float


@dataclass
class Pool:
    """The VMs of one hypervisor: warm ones per size class, leased ones per
    task. A VM serves exactly one task and is destroyed when it ends.

    Args:
        instance: the Infinito.Nexus instance this broker serves.
        broker: the id of this broker process.
        lease_seconds: how long a lease lives without renewal.
    """

    instance: str
    broker: str
    lease_seconds: float
    warm: dict[str, list[str]] = field(default_factory=dict)
    leases: dict[str, Lease] = field(default_factory=dict)

    def assign(self, task: Task, size_class: str, now: float) -> Lease | None:
        """Lease a warm VM of ``size_class`` to ``task``; None when the pool is
        empty and the caller clones from the template."""
        if any(lease.task == task for lease in self.leases.values()):
            raise LeaseError(f"task {task.kind}/{task.ref} already holds a VM")
        warm = self.warm.get(size_class) or []
        if not warm:
            return None
        return self.lease(warm.pop(0), task, now)

    def lease(self, vm: str, task: Task, now: float) -> Lease:
        """Bind ``vm`` to ``task``; a VM that already serves a task is refused."""
        if vm in self.leases:
            raise LeaseError(f"{vm} already serves {self.leases[vm].task.ref}")
        lease = Lease(vm, task, self.instance, self.broker, now + self.lease_seconds)
        self.leases[vm] = lease
        return lease

    def release(self, task: Task) -> str:
        """End ``task`` and return the VM to destroy; it never rejoins the pool."""
        for vm, lease in list(self.leases.items()):
            if lease.task == task:
                del self.leases[vm]
                return vm
        raise LeaseError(f"task {task.kind}/{task.ref} holds no VM")

    def orphans(self, vms: list[str], now: float) -> list[str]:
        """Return the VMs of ``vms`` that carry no live lease of this instance:
        after a broker restart these are destroyed and their tokens revoked."""
        warm = {vm for names in self.warm.values() for vm in names}
        return sorted(
            vm
            for vm in vms
            if vm not in warm
            and not (
                vm in self.leases
                and self.leases[vm].instance == self.instance
                and self.leases[vm].expiry > now
            )
        )

    def shortfall(self, targets: dict[str, int]) -> dict[str, int]:
        """Return per size class how many VMs to clone so the warm pool holds
        the count the inventory names."""
        return {
            size: count - len(self.warm.get(size) or [])
            for size, count in targets.items()
            if count > len(self.warm.get(size) or [])
        }
