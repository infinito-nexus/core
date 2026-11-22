import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.domains.default_primary import default_domain_primary

ROLE = PROJECT_ROOT / "roles/web-app-xwiki"
DOCKERFILE = ROLE / "files/Dockerfile"
STAGE_TASKS = ROLE / "tasks/00_core.yml"
PATH_ABSOLUTE = re.compile(r"lookup\('path_absolute', '([^']+)'\)")
IMAGE_DIRS = ("/usr/local/xwiki/data", "/usr/local/tomcat/webapps")
CA_NAME = default_domain_primary()
CA_PEM = "ROOT-CA-PEM"
PUBLIC_ROOTS = "public-roots PUBLIC-PEM"
PRE_FIX_DOCKERFILE = """ARG XWIKI_IMAGE
ARG XWIKI_VERSION
FROM ${XWIKI_IMAGE}:${XWIKI_VERSION}
COPY xwiki-entrypoint.sh /usr/local/bin/infinito-xwiki-entrypoint.sh
RUN chmod 0755 /usr/local/bin/infinito-xwiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/infinito-xwiki-entrypoint.sh"]
CMD ["xwiki"]
"""
KEYTOOL = """#!/bin/sh
mode=""
alias=""
file=""
store=""
while [ $# -gt 0 ]; do
  case "$1" in
    -importcert|-list) mode="$1" ;;
    -alias) alias="$2"; shift ;;
    -file) file="$2"; shift ;;
    -keystore) store="$2"; shift ;;
  esac
  shift
done
case "$mode" in
  -importcert) printf '%s %s\\n' "$alias" "$(cat "$file")" >> "$store" ;;
  -list) grep -q "^$alias " "$store" ;;
  *) exit 2 ;;
esac
"""
STOCK_ENTRYPOINT = """#!/bin/sh
printf 'argv=%s\\n' "$*"
cat "$JAVA_HOME/lib/security/cacerts"
"""


def walk(tasks):
    for task in tasks:
        yield task
        yield from walk(task.get("block", []))


def staged_build_context():
    """
    Returns:
        Build-context file name mapped to the repository file the stage task
        copies under that name.
    """
    stage = next(
        task for task in walk(load_yaml_any(STAGE_TASKS)) if "stack_host_copy" in task
    )
    context = {}
    for item in stage["loop"]:
        match = PATH_ABSOLUTE.search(item)
        source = PROJECT_ROOT / match.group(1) if match else ROLE / "files" / item
        context[source.name] = source
    return context


def instructions(dockerfile):
    """
    Args:
        dockerfile: text of the Dockerfile the image is built from.

    Returns:
        The COPY targets mapped to their build-context names, and the argv the
        container starts with (ENTRYPOINT followed by CMD).
    """
    copies = {}
    entrypoint = []
    cmd = []
    for line in dockerfile.splitlines():
        keyword, _, rest = line.partition(" ")
        if keyword == "COPY":
            source, target = rest.split()
            copies[target] = source
        elif keyword == "ENTRYPOINT":
            entrypoint = json.loads(rest)
        elif keyword == "CMD":
            cmd = json.loads(rest)
    return copies, entrypoint + cmd


def write_executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class TestXWikiImageJvmTrust(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.jre = self.root / "jre"
        write_executable(self.jre / "bin/keytool", KEYTOOL)
        (self.jre / "lib/security").mkdir(parents=True)
        (self.jre / "lib/security/cacerts").write_text(f"{PUBLIC_ROOTS}\n")
        write_executable(self.root / "bin/docker-entrypoint.sh", STOCK_ENTRYPOINT)
        self.ca = self.root / "root-ca.crt"
        self.ca.write_text(CA_PEM)

    def boot(self, dockerfile, with_platform_ca):
        """
        Args:
            dockerfile: text of the Dockerfile whose image start is replayed.
            with_platform_ca: whether the deploy mounts the self-signed root CA.

        Returns:
            The truststore the stock XWiki entrypoint hands to Tomcat's JVM and
            the argv it receives.
        """
        context = staged_build_context()
        copies, argv = instructions(dockerfile)
        image = self.root / "image"
        for target, name in copies.items():
            text = read_text(str(context[name]))
            for image_dir in IMAGE_DIRS:
                text = text.replace(image_dir, str(image / image_dir.lstrip("/")))
            write_executable(image / target.lstrip("/"), text)
        env = {
            "PATH": f"{self.root / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "JAVA_HOME": str(self.jre),
            "XWIKI_PROPERTIES_SOURCE": str(self.root / "absent/xwiki.properties"),
            "CA_TRUST_NAME": CA_NAME,
        }
        if with_platform_ca:
            env["CA_TRUST_CERT"] = str(self.ca)
        done = subprocess.run(
            [str(image / arg.lstrip("/")) if arg in copies else arg for arg in argv],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.splitlines()
        return lines[1:], lines[0]

    def test_tomcat_jvm_trusts_the_platform_root_ca_for_the_oidc_token_call(self):
        truststore, argv = self.boot(read_text(str(DOCKERFILE)), with_platform_ca=True)
        self.assertEqual(truststore, [PUBLIC_ROOTS, f"{CA_NAME} {CA_PEM}"])
        self.assertEqual(argv, "argv=xwiki")

    def test_without_a_platform_ca_xwiki_starts_on_the_stock_truststore(self):
        truststore, argv = self.boot(read_text(str(DOCKERFILE)), with_platform_ca=False)
        self.assertEqual(truststore, [PUBLIC_ROOTS])
        self.assertEqual(argv, "argv=xwiki")

    def test_the_pre_fix_image_starts_tomcat_without_the_platform_root_ca(self):
        truststore, argv = self.boot(PRE_FIX_DOCKERFILE, with_platform_ca=True)
        self.assertEqual(truststore, [PUBLIC_ROOTS])
        self.assertEqual(argv, "argv=xwiki")


if __name__ == "__main__":
    unittest.main()
