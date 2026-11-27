import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from . import PROJECT_ROOT

COSMOS_SKY = PROJECT_ROOT / "roles/test-e2e-playwright/files/cosmos-sky.js"
HTML_SPEC = PROJECT_ROOT / "roles/web-svc-html/files/playwright/test-design.js"
INTERNALS = PROJECT_ROOT / "tests/unit/javascript/utils/internals.js"

DRIVER = textwrap.dedent(
    """
    const { loadInternals } = require(process.env.INTERNALS);
    const LEGIBLE = "data-cosmos-legible";
    const attributes = new Map();
    const observers = new Set();
    let deliveries = 0;
    class MutationObserver {
      constructor(callback) {
        this.callback = callback;
        this.pending = false;
      }
      observe(target, { attributeFilter }) {
        this.filter = attributeFilter;
        observers.add(this);
      }
      disconnect() {
        observers.delete(this);
      }
      queue(name) {
        if (!this.filter.includes(name) || this.pending) return;
        this.pending = true;
        queueMicrotask(() => {
          this.pending = false;
          deliveries += 1;
          if (deliveries > 50) throw new Error("observers keep rewriting the attribute");
          if (observers.has(this)) this.callback([]);
        });
      }
    }
    const root = {
      getAttribute: (name) => attributes.get(name) ?? null,
      setAttribute: (name, value) => {
        attributes.set(name, String(value));
        for (const observer of observers) observer.queue(name);
      },
    };
    const globals = { document: { documentElement: root }, MutationObserver };
    const shared = loadInternals(process.env.COSMOS_SKY, ["COSMOS_SKY", "TRANSPARENT", "pinLegible"], {}, globals);
    const { pinLegible } = process.env.SPEC
      ? loadInternals(process.env.SPEC, ["pinLegible"], { "./cosmos-sky": shared }, { document: globals.document, MutationObserver })
      : shared;
    const page = { evaluate: async (callback, argument) => callback(argument) };
    const minuteTick = (band) =>
      new Promise((resolve) =>
        setTimeout(() => {
          root.setAttribute(LEGIBLE, band);
          setTimeout(resolve, 0);
        }, 0),
      );
    const scenarios = {
      unpinned: async () => {
        root.setAttribute(LEGIBLE, "top");
        await minuteTick("all");
      },
      pinned: async () => {
        await pinLegible(page, "top");
        await minuteTick("all");
      },
      repinned: async () => {
        await pinLegible(page, "top");
        await pinLegible(page, "all");
        await minuteTick("top");
      },
    };
    scenarios[process.env.SCENARIO]().then(
      () => process.stdout.write(`RESULT:${root.getAttribute(LEGIBLE)}\\n`),
      (error) => process.stdout.write(`ERROR:${error.message}\\n`),
    );
    """
)


def _have_node() -> bool:
    return shutil.which("node") is not None


@unittest.skipUnless(_have_node(), "node is not available in PATH")
class TestPinLegibleSurvivesTheSkyRefresh(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "run.js").write_text(DRIVER)

    def _run(self, scenario: str, spec: Path | None = None) -> str:
        """Args:
            scenario: `unpinned` sets the band by hand, `pinned` pins `top`, `repinned` pins `top` then `all`; the sky's minute tick then writes its own band.
            spec: a role spec whose `pinLegible` pins instead of the shared helper's.

        Returns:
            The driver's stdout: RESULT:<band left on the root> or ERROR:<message>.
        """
        proc = subprocess.run(
            ["node", "run.js"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SCENARIO": scenario,
                "COSMOS_SKY": str(COSMOS_SKY),
                "INTERNALS": str(INTERNALS),
                "SPEC": str(spec) if spec else "",
            },
            cwd=self.root,
            timeout=30,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_negative_control_the_minute_tick_rewrites_a_band_set_by_hand(
        self,
    ) -> None:
        self.assertIn("RESULT:all", self._run("unpinned"))

    def test_a_minute_tick_after_the_pin_leaves_the_pinned_band(self) -> None:
        self.assertIn("RESULT:top", self._run("pinned"))

    def test_a_later_pin_replaces_the_earlier_one_instead_of_fighting_it(
        self,
    ) -> None:
        self.assertIn("RESULT:all", self._run("repinned"))

    def test_the_web_svc_html_spec_pin_survives_a_minute_tick(self) -> None:
        self.assertIn("RESULT:top", self._run("pinned", HTML_SPEC))


if __name__ == "__main__":
    unittest.main()
