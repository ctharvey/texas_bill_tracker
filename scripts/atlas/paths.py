"""Repository locations, from this file's place in scripts/atlas/ (the units extract scripts/ beside data/)."""
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parent
