from __future__ import annotations

import unittest
from typing import Any, ClassVar

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.files import PROJECT_ROOT
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

_ROLE_VARS = PROJECT_ROOT / "roles" / "svc-opt-swapfile" / ROLE_FILE_VARS_MAIN
_MIB = 1024**2
_GIB = 1024**3
_RAM_MIB = 15934
_RAM_REQUEST = f"{_RAM_MIB}M"
_DRIFTS_MIB = (-2, 7)


def _swapon(*entries: tuple[str, str, int]) -> dict[str, Any]:
    """Return the ``swapfile_active`` register of ``swapon --show=NAME,TYPE,SIZE``.

    Args:
        entries: ``(name, type, size_bytes)`` per active swap area, with the
            name escaped the way ``swapon --raw`` prints it.

    Returns:
        The register with ``stdout`` and ``stdout_lines`` as Ansible sets them.
    """
    stdout = "\n".join(f"{name} {kind} {size}" for name, kind, size in entries)
    return {"rc": 0, "stdout": stdout, "stdout_lines": stdout.splitlines()}


class TestActiveSwapfileMatch(unittest.TestCase):
    declared: ClassVar[dict[str, Any]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.declared = DataLoader().load_from_file(
            str(_ROLE_VARS), trusted_as_template=True
        )

    def _resolve(self, name: str, size: str, active: dict[str, Any]) -> Any:
        """Resolve one variable of ``vars/main.yml`` through Ansible's Templar.

        Args:
            name: the variable to resolve, e.g. ``SWAPFILE_ACTIVE_MATCH``.
            size: the requested ``SWAPFILE_SIZE`` swap-forge would receive.
            active: the ``swapfile_active`` register.

        Returns:
            The rendered value with its native type.
        """
        variables = {
            **self.declared,
            "SWAPFILE_SIZE": size,
            "swapfile_active": active,
        }
        templar = Templar(loader=DataLoader(), variables=variables)
        return templar.template(self.declared[name])

    def _match(self, size: str, active: dict[str, Any]) -> Any:
        """Resolve ``SWAPFILE_ACTIVE_MATCH``.

        Args:
            size: the requested ``SWAPFILE_SIZE``.
            active: the ``swapfile_active`` register.

        Returns:
            The sizes in bytes of the active swapfiles that meet the request.
        """
        return self._resolve("SWAPFILE_ACTIVE_MATCH", size, active)

    def test_a_ram_sized_file_that_drifted_a_few_mib_is_kept(self) -> None:
        for drift in _DRIFTS_MIB:
            size = (_RAM_MIB + drift) * _MIB
            with self.subTest(drift_mib=drift):
                self.assertEqual(
                    self._match(_RAM_REQUEST, _swapon(("/swapfile", "file", size))),
                    [size],
                )

    def test_an_exact_mib_comparison_recreates_the_drifted_file(self) -> None:
        requested = self._resolve("SWAPFILE_SIZE_BYTES", _RAM_REQUEST, _swapon())
        drifted = [(_RAM_MIB + drift) * _MIB for drift in _DRIFTS_MIB]
        self.assertEqual(
            [size for size in drifted if size // _MIB == requested // _MIB],
            [],
            "swap-forge 1.0.1 compares whole MiB, so every drifted file reads as "
            "the wrong size and is swapped off to be recreated",
        )

    def test_no_active_swap_matches_nothing(self) -> None:
        self.assertEqual(self._match(_RAM_REQUEST, _swapon()), [])

    def test_a_partition_or_zram_of_the_requested_size_is_not_a_swapfile(
        self,
    ) -> None:
        for name in ("/dev/zram0", "/dev/sda2"):
            with self.subTest(name=name):
                active = _swapon((name, "partition", _RAM_MIB * _MIB))
                self.assertEqual(self._match(_RAM_REQUEST, active), [])

    def test_a_file_half_the_requested_size_is_replaced(self) -> None:
        active = _swapon(("/swapfile", "file", _RAM_MIB * _MIB // 2))
        self.assertEqual(self._match(_RAM_REQUEST, active), [])

    def test_an_exact_mib_pin_matches_its_file(self) -> None:
        active = _swapon(("/swapfile", "file", 2048 * _MIB))
        self.assertEqual(self._match("2048M", active), [2048 * _MIB])

    def test_a_lowercase_unit_is_read_as_binary_gib(self) -> None:
        active = _swapon(("/swapfile", "file", 64 * _GIB))
        self.assertEqual(self._match("64gb", active), [64 * _GIB])

    def test_an_escaped_space_in_the_file_name_keeps_the_columns(self) -> None:
        size = _RAM_MIB * _MIB
        active = _swapon(
            ("/var/lib/swap\\x20space/swapfile", "file", size),
            ("/dev/zram0", "partition", size),
        )
        self.assertEqual(self._match(_RAM_REQUEST, active), [size])


if __name__ == "__main__":
    unittest.main()
