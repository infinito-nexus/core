import pathlib
import tempfile
import unittest
import unittest.mock as mock

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


class TestOomGuard(unittest.TestCase):
    def test_the_oom_kill_counter_comes_from_vmstat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "vmstat").write_text(
                "nr_free_pages 1\noom_kill 3\npswpin 0\n", encoding="utf-8"
            )
            self.assertEqual(probes.oom_kills(root), 3)

    def test_a_missing_vmstat_has_no_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(probes.oom_kills(pathlib.Path(tmp)))

    def test_only_the_runner_agent_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for pid, name in (
                (5, "Runner.Listener"),
                (9, "Runner.Worker"),
                (12, "ruby"),
            ):
                (root / str(pid)).mkdir()
                (root / str(pid) / "comm").write_text(f"{name}\n", encoding="utf-8")
            self.assertEqual(probes.runner_pids(root), ["5", "9"])

    def test_protection_keeps_only_the_pids_choom_accepted(self) -> None:
        def choom(argv: list[str], **_kwargs: object) -> mock.Mock:
            return mock.Mock(returncode=0 if argv[-1] == "5" else 1)

        with mock.patch.object(probes.subprocess, "run", side_effect=choom) as run:
            self.assertEqual(probes.protect_from_oom(["5", "9"]), ["5"])
        self.assertEqual(
            run.call_args_list[0].args[0],
            ["sudo", "-n", "choom", "-n", "-1000", "-p", "5"],
        )

    def test_the_kernel_log_yields_only_its_oom_lines(self) -> None:
        dmesg = (
            "[1.0] usb 1-1: new device\n"
            "[2.0] Out of memory: Killed process 42 (ruby)\n"
            "[3.0] Memory cgroup out of memory: Killed process 51 (node)\n"
        )
        with mock.patch.object(
            probes.subprocess, "run", return_value=mock.Mock(stdout=dmesg)
        ):
            self.assertEqual(
                probes.oom_victims(1),
                ["[3.0] Memory cgroup out of memory: Killed process 51 (node)"],
            )


if __name__ == "__main__":
    unittest.main()
