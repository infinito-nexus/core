import subprocess
import unittest
import unittest.mock as mock

from infinito_elector_src import roles


class _Fixed(roles.Role):
    def __init__(self, peers):
        self.peers = peers

    def is_ready_to_compete(self):
        return True

    def become_writer(self):
        return None

    def become_read_only(self):
        return None

    def is_writable(self):
        return False

    def rank(self):
        return 0

    def peer_ranks(self):
        return {}

    def follow(self, writer):
        return None


class TestQuorum(unittest.TestCase):
    def test_three_instances_need_two(self):
        self.assertEqual(_Fixed(("b", "c")).quorum(), 2)

    def test_five_instances_need_three(self):
        self.assertEqual(_Fixed(("b", "c", "d", "e")).quorum(), 3)

    def test_single_instance_needs_itself(self):
        self.assertEqual(_Fixed(()).quorum(), 1)


class TestChoose(unittest.TestCase):
    def test_highest_rank_wins(self):
        self.assertEqual(roles.choose({"a": 1, "b": 3, "c": 2}), "b")

    def test_equal_ranks_go_to_the_lowest_host_id(self):
        self.assertEqual(roles.choose({"c": 5, "a": 5, "b": 4}), "a")

    def test_no_candidate_is_refused(self):
        with self.assertRaises(ValueError):
            roles.choose({})


class TestRunCommand(unittest.TestCase):
    def test_returns_stdout(self):
        done = subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
        with mock.patch.object(roles.subprocess, "run", return_value=done) as run:
            self.assertEqual(roles.run_command(["true"], stdin="x"), "ok\n")
        self.assertEqual(run.call_args.kwargs["input"], "x")

    def test_non_zero_exit_raises_role_error(self):
        done = subprocess.CompletedProcess([], 2, stdout="", stderr="denied\n")
        with (
            mock.patch.object(roles.subprocess, "run", return_value=done),
            self.assertRaisesRegex(roles.RoleError, "exited 2: denied"),
        ):
            roles.run_command(["mariadb"])

    def test_timeout_raises_role_error(self):
        timeout = subprocess.TimeoutExpired("x", 5)
        with (
            mock.patch.object(roles.subprocess, "run", side_effect=timeout),
            self.assertRaises(roles.RoleError),
        ):
            roles.run_command(["mariadb"])


if __name__ == "__main__":
    unittest.main()
