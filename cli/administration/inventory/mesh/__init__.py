"""Cross-host credential generation.

Every other generator in this package is single-host scoped: it is handed one
``host_vars`` file and mints secrets that depend on nothing outside it. A mesh
credential breaks that assumption, because the value one host receives is
derived from a secret minted for a different host -- a peer holds the public
half of a key whose private half lives somewhere else.

This package is the single writer that sees the whole host set at once, so a
mesh is always written complete or not at all. It knows nothing about
WireGuard: a mesh is a named hub-and-spoke grouping of inventory hosts, each
member carrying a keypair and the public halves of the peers it may reach.
"""

from .model import Mesh, MeshMember, MeshSpec
from .plan import plan_mesh
from .write import existing_public_keys, write_mesh

__all__ = [
    "Mesh",
    "MeshMember",
    "MeshSpec",
    "existing_public_keys",
    "plan_mesh",
    "write_mesh",
]
