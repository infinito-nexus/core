"""The one GitLab ``rails runner`` that realigns root, ensures the platform
administrator and converges the appearance.

The stdin of ``tasks/utils/platform_admin.yml`` is rendered the way Ansible renders it and
run under ``eval($stdin.read, TOPLEVEL_BINDING, "stdin")``, which is what
``rails runner -`` does, against stub models. The scripts end early with
``exit(0)`` and fail with ``abort``; one boot is only equivalent to three if
neither ends the run for the steps behind it.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-gitlab"
TASKS = ROLE / "tasks" / "utils" / "platform_admin.yml"

STUBS = """
require 'json'

class String
  def present?
    !empty?
  end
end

class StubUser
  attr_accessor :password_confirmation, :password_automatically_set
  attr_writer :admin, :password

  def initialize(password, admin)
    @password = password
    @admin = admin
    @password_automatically_set = false
  end

  def valid_password?(candidate)
    candidate == @password
  end

  def password_automatically_set?
    @password_automatically_set
  end

  def admin?
    @admin
  end

  def save!
    true
  end
end

STUB_USERS = JSON.parse(ENV.fetch('STUB_USERS')).transform_values { |password, admin| StubUser.new(password, admin) }

module User
  def self.find_by_username(name)
    STUB_USERS[name]
  end

  def self.find_by_any_email(_email)
    nil
  end
end

class Appearance
  TEXTS = %i[title pwa_name pwa_short_name].freeze
  UPLOADS = %i[logo header_logo favicon pwa_icon].freeze
  Upload = Struct.new(:file)

  attr_writer(*TEXTS, *UPLOADS)

  def self.first
    new
  end

  TEXTS.each { |field| define_method(field) { instance_variable_get("@#{field}").to_s } }
  UPLOADS.each { |field| define_method(field) { Upload.new(nil) } }

  def save!
    true
  end
end

eval($stdin.read, TOPLEVEL_BINDING, 'stdin')
"""


def _runner_stdin(design_enabled: bool, design_files: list[dict]) -> str:
    """Render the runner task's stdin with Ansible's block trimming.

    Args:
        design_enabled: value of ``GITLAB_DESIGN_ENABLED``
        design_files: ``gitlab_design_files.results`` of the slurp loop

    Returns:
        the Ruby program the task feeds ``rails runner -``
    """
    task = next(
        task for task in load_yaml_any(str(TASKS)) if "ansible.builtin.command" in task
    )
    environment = Environment(
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    environment.filters["to_json"] = json.dumps

    def lookup(kind: str, relative: str) -> str:
        assert kind == "file", kind
        return read_text(str(ROLE / "files" / relative)).rstrip()

    return environment.from_string(task["ansible.builtin.command"]["stdin"]).render(
        lookup=lookup,
        GITLAB_DESIGN_ENABLED=design_enabled,
        gitlab_design_files={"results": design_files},
    )


@unittest.skipUnless(shutil.which("ruby"), "needs a ruby interpreter")
class TestRailsSteps(unittest.TestCase):
    def _run(
        self,
        users: dict[str, list],
        title: str = "",
        design_enabled: bool = False,
        design_files: list[dict] | None = None,
    ) -> subprocess.CompletedProcess:
        env = {
            "PATH": os.environ["PATH"],
            "STUB_USERS": json.dumps(users),
            "GITLAB_ROOT_USERNAME": "root",
            "GITLAB_ROOT_PASSWORD": "stub-root-secret",
            "GITLAB_ADMIN_USERNAME": "administrator",
            "GITLAB_ADMIN_EMAIL": "administrator@example.invalid",
            "GITLAB_ADMIN_NAME": "Platform Administrator",
            "GITLAB_ADMIN_PASSWORD": "stub-admin-secret",
            "GITLAB_DESIGN_TITLE": title,
        }
        return subprocess.run(
            ["ruby", "-e", STUBS],
            input=_runner_stdin(design_enabled, design_files or []),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_three_unchanged_steps_each_report_and_nothing_changes(self) -> None:
        result = self._run(
            {
                "root": ["stub-root-secret", True],
                "administrator": ["stub-admin-secret", True],
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        for label in ("realign_root_password", "ensure_platform_admin", "appearance"):
            self.assertRegex(result.stdout, rf"(?m)^{label}: \[UNCHANGED\] ")
        self.assertNotRegex(result.stdout, r"\[CHANGED\]|\[FAIL\]")

    def test_a_failed_root_realign_still_reports_the_other_steps(self) -> None:
        result = self._run({"administrator": ["drifted", False]})

        self.assertNotEqual(result.returncode, 0)
        self.assertRegex(
            result.stdout,
            r"(?m)^realign_root_password: \[FAIL\] no GitLab user named 'root'$",
        )
        self.assertRegex(
            result.stdout,
            r"(?m)^ensure_platform_admin: \[CHANGED\] administrator: admin, password$",
        )
        self.assertRegex(result.stdout, r"(?m)^appearance: \[UNCHANGED\] ")
        self.assertIn("[FAIL] failed steps: realign_root_password", result.stderr)

    def test_the_uploads_reach_the_appearance_step(self) -> None:
        result = self._run(
            {
                "root": ["stub-root-secret", True],
                "administrator": ["stub-admin-secret", True],
            },
            title="Infinito",
            design_enabled=True,
            design_files=[
                {
                    "item": {"field": "logo", "ext": "png", "file": "logo.png"},
                    "content": base64.b64encode(b"logo").decode(),
                },
                {"item": {"field": "favicon", "ext": "ico", "file": "favicon.ico"}},
            ],
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"(?m)^appearance: \[CHANGED\] ")
        self.assertEqual(
            re.findall(r"(?m)^(\w+): \[CHANGED\]", result.stdout), ["appearance"]
        )


if __name__ == "__main__":
    unittest.main()
