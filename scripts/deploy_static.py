"""Publish public GitHub main atomically; run as the dedicated Linux site user."""

import fcntl
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path


ROOT = Path('/var/www/html/texas-bill-atlas')
STATE = Path('/var/lib/texas-bill-atlas')
REPOSITORY = STATE / 'repository.git'
FILES = ('index.html', 'src/app.js', 'src/taxonomy.js', 'src/styles.css', 'src/review.js', 'data/bills.json')
KEEP_RELEASES = 10


def git(*args: str) -> bytes:
    return subprocess.run(
        ['git', '--git-dir', str(REPOSITORY), *args], check=True, capture_output=True, timeout=120,
    ).stdout


def main() -> None:
    with (STATE / 'deploy.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not REPOSITORY.exists():
            subprocess.run(['git', 'init', '--bare', str(REPOSITORY)], check=True, timeout=30)
        git('fetch', '--depth=1', 'https://github.com/ctharvey/texas_bill_tracker.git',
            '+refs/heads/main:refs/heads/main')
        commit = git('rev-parse', 'refs/heads/main').decode().strip()
        release = ROOT / 'releases' / commit
        current = ROOT / 'current'
        if current.is_symlink() and current.resolve() == release:
            print('Already current:', commit)
            return
        bundle = {name: git('show', f'{commit}:{name}') for name in FILES}
        snapshot = json.loads(bundle['data/bills.json'])
        datetime.fromisoformat(snapshot['generated_at'].replace('Z', '+00:00'))
        bills = snapshot.get('bills', [])
        ids = [bill.get('id', '') for bill in bills]
        if (snapshot.get('session') != '90R' or snapshot.get('data_mode') != 'official-ftp'
                or len(bills) < 1000 or len(set(ids)) != len(ids)
                or not all(re.fullmatch(r'(?:HB|SB|HJR|SJR|HCR|SCR|HR|SR)\d{1,5}', key) for key in ids)):
            raise ValueError('Refusing incomplete, curated or invalid legislative snapshot')
        for name in FILES[:-1]:
            if not bundle[name].strip():
                raise ValueError('Empty application asset: ' + name)
        release.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=release.parent))
        try:
            staging.chmod(0o755)
            for name, content in bundle.items():
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o644)
            # Server-written data (live/bills.json, live/luna/tags.json) outlives releases.
            (staging / 'live').symlink_to(Path('..') / '..' / 'live', target_is_directory=True)
            if not release.exists():
                staging.rename(release)
            link = ROOT / '.next'
            link.unlink(missing_ok=True)
            link.symlink_to(Path('releases') / commit, target_is_directory=True)
            os.replace(link, current)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        print('Published:', commit, 'records:', len(bills), 'snapshot:', snapshot['generated_at'])
        prune(release.parent, current.resolve())


def prune(releases: Path, live: Path, keep: int = KEEP_RELEASES) -> None:
    # Called with the deploy lock held, so every .staging-* left is from a crashed run.
    try:
        for leftover in releases.glob('.staging-*'):
            shutil.rmtree(leftover, ignore_errors=True)
        built = sorted((p for p in releases.iterdir() if p.is_dir() and re.fullmatch(r'[0-9a-f]{40}', p.name)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for old in built[keep:]:
            if old.resolve() != live:
                shutil.rmtree(old)
    except OSError as error:
        print('Release pruning skipped:', type(error).__name__)  # Never fail a successful publish.


if __name__ == '__main__':
    main()
