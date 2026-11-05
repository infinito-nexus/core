"""Swarm adapter of the failover suite: fault injection, checker service, lab sizes."""

from __future__ import annotations

from utils.failover.swarm.backup import Backup
from utils.failover.swarm.client import Clients
from utils.failover.swarm.commands import filter_lab_overrides, load_lab_sizes
from utils.failover.swarm.engine_ops import EngineOps
from utils.failover.swarm.lab import SwarmLabBase
from utils.failover.swarm.topology import Topology

__all__ = ["SwarmLab", "filter_lab_overrides", "load_lab_sizes"]


class SwarmLab(Backup, Topology, EngineOps, Clients, SwarmLabBase):
    """Lab adapter driving the DinD Swarm lab from the lab host; see ``SwarmLabBase``."""
