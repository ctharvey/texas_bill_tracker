"""Compare every computed style of two commits in a throwaway Playwright container on the active docker context
(ubuntu-server here). A CSS move passes when the result is IDENTICAL.

Usage: python tests/e2e/run_style_parity.py BASE [CANDIDATE] [--mode bundle|src] [--workers N]

Both trees come from git archive, so uncommitted edits are never measured. The candidate's style_snapshot.py measures
both trees (the base may predate it). Comparing a commit with itself checks that the snapshot is deterministic.
"""

import argparse
import secrets
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
IMAGE = "mcr.microsoft.com/playwright/python:v1.58.0-noble"  # Same as run_remote.py and CI.
PACKAGES = "playwright==1.58.0"
SCRIPT = "tests/e2e/style_snapshot.py"

INSIDE = r"""set -e
mkdir -p /w && cd /w && tar xif -
cp b/{script} a/{script}
for t in a b; do (cd $t && git init -q && git add -A); done
pip install -q --disable-pip-version-check --root-user-action=ignore --break-system-packages {packages}
export CI=true
python3 a/{script} snap /w/a.json.gz --mode {mode} --workers {workers} & A=$!
python3 b/{script} snap /w/b.json.gz --mode {mode} --workers {workers} & B=$!
wait $A || echo "A: snapshot reported errors"
wait $B || echo "B: snapshot reported errors"
exec python3 b/{script} compare /w/a.json.gz /w/b.json.gz --trees /w/a /w/b --mode {mode}
"""


def sha(ref):
    return subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", ref], capture_output=True, text=True,
                          check=True).stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("candidate", nargs="?", default="HEAD")
    parser.add_argument("--mode", default="bundle", choices=["bundle", "src"])
    parser.add_argument("--workers", type=int, default=3, help="browsers per tree; both trees run at once")
    opts = parser.parse_args()

    base, cand = sha(opts.base), sha(opts.candidate)
    name = f"tba-style-{base}-{cand}-{secrets.token_hex(3)}"
    script = INSIDE.format(script=SCRIPT, packages=PACKAGES, mode=opts.mode, workers=opts.workers)
    print(f"Style parity A={base} B={cand} ({opts.mode}) in {name}", flush=True)

    # Two archives back to back; tar -i reads past the first one's end-of-archive blocks.
    archives = [subprocess.Popen(["git", "-C", str(REPO), "archive", "--format=tar", f"--prefix={p}/", ref],
                                 stdout=subprocess.PIPE) for p, ref in (("a", base), ("b", cand))]
    run = ["docker", "run", "-i", "--rm", "--init", "--name", name, "--shm-size=2g", "--memory=12g", "--cpus=6",
           IMAGE, "bash", "-c", script]
    proc = subprocess.Popen(run, stdin=subprocess.PIPE)
    try:
        for archive in archives:
            for chunk in iter(lambda a=archive: a.stdout.read(1 << 16), b""):
                proc.stdin.write(chunk)
            archive.wait()
        proc.stdin.close()
        code = proc.wait()
    except KeyboardInterrupt:
        code = 130
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
