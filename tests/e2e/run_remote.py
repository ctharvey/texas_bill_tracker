"""Run the browser E2E for one commit in a throwaway Playwright container on the active docker context (ubuntu-server
here), so the desktop does none of the work.

Usage: python tests/e2e/run_remote.py [commit] [-n WORKERS] [--viewports all|desktop|phone|default] [-- pytest args]

The container gets the commit's tracked files (git archive), so uncommitted edits are never tested. Its exit code is
pytest's; the container is removed afterwards, also on Ctrl-C.
"""

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IMAGE = "mcr.microsoft.com/playwright/python:v1.58.0-noble"  # Same Playwright as CI (.github/workflows/tests.yml).
PACKAGES = "pytest==9.0.3 pytest-xdist==3.8.0 playwright==1.58.0"

INSIDE = r"""set -e
mkdir -p /w && cd /w && tar xf -
git init -q && git add -A   # harness.release_files() lists the release with git ls-files
pip install -q --disable-pip-version-check --root-user-action=ignore --break-system-packages {packages}
export CI=true TBA_E2E=1 {viewports}
exec python3 -m pytest -q -n {workers} -p no:cacheprovider -rfE {args}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("commit", nargs="?", default="HEAD")
    parser.add_argument("-n", "--workers", type=int, default=6)
    parser.add_argument("--viewports", default="all", choices=["all", "desktop", "phone", "default"])
    parser.add_argument("pytest_args", nargs="*", help="after --; default tests/e2e")
    opts = parser.parse_args()

    sha = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", opts.commit],
                         capture_output=True, text=True, check=True).stdout.strip()
    context = subprocess.run(["docker", "context", "show"], capture_output=True, text=True).stdout.strip()
    name = f"tba-e2e-{sha}-{secrets.token_hex(3)}"
    viewports = "" if opts.viewports == "default" else f"TBA_E2E_VIEWPORTS={opts.viewports}"
    script = INSIDE.format(packages=PACKAGES, viewports=viewports, workers=opts.workers,
                           args=" ".join(opts.pytest_args) or "tests/e2e")
    print(f"E2E {sha} in {name} on docker context {context!r}, -n {opts.workers}, viewports {opts.viewports}", flush=True)

    archive = subprocess.Popen(["git", "-C", str(REPO), "archive", "--format=tar", sha], stdout=subprocess.PIPE)
    run = ["docker", "run", "-i", "--rm", "--init", "--name", name, "--shm-size=2g", "--memory=12g", "--cpus=6",
           IMAGE, "bash", "-c", script]
    try:
        code = subprocess.run(run, stdin=archive.stdout).returncode
    except KeyboardInterrupt:
        code = 130
    finally:
        archive.stdout.close()
        archive.wait()
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
