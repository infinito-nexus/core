from __future__ import annotations

from pathlib import Path
from unittest import TestCase, main, mock

import cli.contributing.security.database.__main__ as database_main


class TestMain(TestCase):
    def _main(self, errors):
        with mock.patch.object(
            database_main, "fetch_databases", return_value=errors
        ) as fetch:
            code = database_main.main(["--dir", "/tmp/db", "--engines", "trivy", "osv"])
        return code, fetch

    def test_the_requested_engines_are_downloaded_into_the_directory(self):
        _code, fetch = self._main([])
        _p, root, engines, _runner, _fetch = fetch.call_args.args
        self.assertEqual((root, engines), (Path("/tmp/db"), ["trivy", "osv"]))

    def test_a_failed_download_fails_the_command(self):
        code, _fetch = self._main(["trivy database: exited 1: no network"])
        self.assertEqual(code, 1)

    def test_an_unknown_engine_is_rejected(self):
        with self.assertRaises(SystemExit):
            database_main.main(["--dir", "/tmp/db", "--engines", "clair"])


if __name__ == "__main__":
    main()
