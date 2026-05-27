import os
import subprocess
import sys
import unittest

from cli.administration.deploy.container import command as deploy_container


class TestEnsureImage(unittest.TestCase):
    @unittest.mock.patch("subprocess.run")
    def test_ensure_image_skips_build_when_image_exists(self, mock_run):
        """
        If the image already exists, ensure_image should only call
        `docker image inspect` and NOT run `docker build`.
        """
        # docker image inspect → rc=0 (image exists)
        mock_run.return_value = subprocess.CompletedProcess(
            args=["docker", "image", "inspect", "infinito:latest"],
            returncode=0,
            stdout="",
            stderr="",
        )

        deploy_container.ensure_image("infinito:latest")

        # Exactly one call: docker image inspect
        self.assertEqual(mock_run.call_count, 1)
        cmd = mock_run.call_args_list[0].args[0]
        self.assertEqual(cmd[:3], ["docker", "image", "inspect"])

        # Ensure docker build was never called
        self.assertFalse(
            any(
                call.args[0][:2] == ["docker", "build"]
                for call in mock_run.call_args_list
            ),
            "docker build should not run when the image already exists",
        )

    @unittest.mock.patch("subprocess.run")
    def test_ensure_image_builds_when_missing(self, mock_run):
        """
        If the image does not exist, ensure_image should call
        `docker image inspect` first and then `docker build`.
        """
        calls: list[list[str]] = []

        def _side_effect(cmd, *args, **kwargs):
            calls.append(cmd)

            # First: docker image inspect → rc=1 (missing)
            if cmd[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=1,
                    stdout="",
                    stderr="missing",
                )

            # Then: docker build → rc=0 (success)
            if cmd[:2] == ["docker", "build"]:
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=0,
                    stdout="",
                    stderr="",
                )

            # Any other commands (should not happen here)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout="",
                stderr="",
            )

        mock_run.side_effect = _side_effect

        deploy_container.ensure_image("infinito:latest")

        self.assertTrue(
            any(c[:3] == ["docker", "image", "inspect"] for c in calls),
            "Expected 'docker image inspect' to be called",
        )
        self.assertTrue(
            any(c[:2] == ["docker", "build"] for c in calls),
            "Expected 'docker build' to run when image is missing",
        )


class TestMain(unittest.TestCase):
    @unittest.mock.patch("cli.administration.deploy.container.command.run_in_container")
    def test_main_requires_forwarded_args(self, mock_run_in_container):
        """
        In 'run' mode, main() must return 1 and not call run_in_container()
        if no deploy arguments are provided after the first '--'.
        """
        argv = [
            "cli.administration.deploy.container.command",
            "run",
            "--image",
            "myimage:latest",
            "--build",
            "--inventory-dir",
            "/tmp/inventory",
            "--",
            # no inventory/deploy args here
        ]
        with unittest.mock.patch.object(sys, "argv", argv):
            rc = deploy_container.main()

        self.assertEqual(rc, 1)
        mock_run_in_container.assert_not_called()

    @unittest.mock.patch("cli.administration.deploy.container.command.run_in_container")
    def test_main_passes_arguments_to_run_in_container(self, mock_run_in_container):
        """
        Ensure that main() correctly splits container args vs inventory/deploy
        args and passes them to run_in_container(). Also ensure inventory_dir
        is forwarded.
        """
        argv = [
            "cli.administration.deploy.container",
            "run",
            "--image",
            "myimage:latest",
            "--build",
            "--inventory-dir",
            "/tmp/inventory",
            "--",
            "--exclude",
            "foo,bar",
            "--",
            "--debug",
        ]

        with unittest.mock.patch.object(sys, "argv", argv):
            rc = deploy_container.main()

        self.assertEqual(rc, 0)
        mock_run_in_container.assert_called_once()

        kwargs = mock_run_in_container.call_args.kwargs

        # Container-level options
        self.assertEqual(kwargs["image"], "myimage:latest")
        self.assertTrue(kwargs["build"])
        self.assertFalse(kwargs["rebuild"])
        self.assertFalse(kwargs["no_cache"])
        self.assertIsNone(kwargs["name"])

        # Inventory dir (new)
        self.assertEqual(kwargs["inventory_dir"], "/tmp/inventory")

        # Inventory args: first segment after first '--' until second '--'
        self.assertEqual(
            kwargs["inventory_args"],
            ["--exclude", "foo,bar"],
        )

        # Deploy args: everything after the second '--'
        self.assertEqual(
            kwargs["deploy_args"],
            ["--debug"],
        )

    @unittest.mock.patch("cli.administration.deploy.container.command.run_in_container")
    def test_main_requires_inventory_dir_when_env_missing(self, mock_run_in_container):
        """
        main() must fail if neither --inventory-dir is provided nor INFINITO_INVENTORY_DIR env is set.
        """
        argv = [
            "cli.administration.deploy.container",
            "run",
            "--image",
            "myimage:latest",
            "--build",
            "--",
            "--exclude",
            "foo,bar",
        ]

        with (
            unittest.mock.patch.dict(os.environ, {}, clear=True),
            unittest.mock.patch.object(sys, "argv", argv),
            self.assertRaises(SystemExit),
        ):
            deploy_container.main()

        mock_run_in_container.assert_not_called()

    @unittest.mock.patch("cli.administration.deploy.container.command.run_in_container")
    def test_main_uses_inventory_dir_from_env_when_present(self, mock_run_in_container):
        """
        If INFINITO_INVENTORY_DIR env is set, --inventory-dir should not be required and the env value
        must be forwarded to run_in_container().
        """
        argv = [
            "cli.administration.deploy.container",
            "run",
            "--image",
            "myimage:latest",
            "--build",
            "--",
            "--exclude",
            "foo,bar",
        ]

        with (
            unittest.mock.patch.dict(
                os.environ, {"INFINITO_INVENTORY_DIR": "/env/inventory"}, clear=True
            ),
            unittest.mock.patch.object(sys, "argv", argv),
        ):
            rc = deploy_container.main()

        self.assertEqual(rc, 0)
        mock_run_in_container.assert_called_once()

        kwargs = mock_run_in_container.call_args.kwargs
        self.assertEqual(kwargs["inventory_dir"], "/env/inventory")


if __name__ == "__main__":
    unittest.main()
