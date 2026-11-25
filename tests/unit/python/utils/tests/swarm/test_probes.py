import pathlib
import tempfile
import unittest

from utils.tests.swarm import probes

_NODE = "a" * 64
_APP = "b" * 64


def _fake_proc(
    root: pathlib.Path, pid: int, name: str, rss: int, swap: int, cg: str
) -> None:
    entry = root / str(pid)
    entry.mkdir()
    (entry / "status").write_text(
        f"Name:\t{name}\nVmRSS:\t{rss} kB\nVmSwap:\t{swap} kB\n", encoding="utf-8"
    )
    (entry / "cgroup").write_text(f"0::{cg}\n", encoding="utf-8")


class TestWriters(unittest.TestCase):
    def test_write_bytes_are_read_per_pid(self) -> None:
        text = (
            "/proc/12/io:write_bytes: 4096\n"
            "/proc/self/io:write_bytes: 1\n"
            "/proc/99/io:write_bytes: 0\n"
        )
        self.assertEqual(probes.parse_write_bytes(text), {"12": 4096, "99": 0})

    def test_top_writers_rank_the_bytes_written_between_snapshots(self) -> None:
        before = {"1": 100, "2": 100, "3": 100}
        after = {"1": 150, "2": 900, "3": 100, "4": 70}
        self.assertEqual(probes.top_writers(before, after, 2), [("2", 800), ("4", 70)])


class TestMemoryByContainer(unittest.TestCase):
    def test_swap_counts_and_the_innermost_container_names_the_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            nested = f"/system.slice/docker-{_NODE}.scope/docker/{_APP}"
            _fake_proc(root, 10, "ollama", 1024, 3072, nested)
            _fake_proc(root, 11, "ollama-runner", 2048, 0, nested)
            _fake_proc(
                root, 12, "dockerd", 512, 0, f"/system.slice/docker-{_NODE}.scope"
            )
            _fake_proc(root, 13, "Runner.Worker", 256, 0, "/user.slice")
            self.assertEqual(
                probes.memory_by_container(root, 3),
                [
                    f"6M ollama({_APP[:12]}, 2)",
                    f"0M dockerd({_NODE[:12]}, 1)",
                    "0M Runner.Worker(host, 1)",
                ],
            )

    def test_kernel_threads_and_vanished_pids_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            _fake_proc(root, 2, "kthreadd", 0, 0, "/")
            (root / "77").mkdir()
            self.assertEqual(probes.memory_by_container(root, 5), [])


class TestZramUsage(unittest.TestCase):
    def test_swapped_and_ram_used_come_from_mm_stat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "zram0").mkdir()
            (root / "zram0" / "mm_stat").write_text(
                f"{12 * 2**30} {3 * 2**30} {4 * 2**30} 0 {4 * 2**30} 0 0 0 0\n",
                encoding="utf-8",
            )
            (root / "sda").mkdir()
            self.assertEqual(probes.zram_usage(root), ["zram0 12288M in 4096M"])

    def test_no_zram_device_yields_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(probes.zram_usage(pathlib.Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
