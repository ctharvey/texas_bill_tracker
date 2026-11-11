"""Publish public GitHub main atomically; run as the dedicated Linux site user."""

import fcntl
import hashlib
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
FILES = ('index.html', 'src/app.js', 'src/taxonomy.js', 'src/styles.css', 'src/review.js', 'src/prefs.js', 'src/sync.js',
         'src/geo.js', 'data/members.json', 'data/geo/districts.json', 'data/geo/house.json', 'data/geo/senate.json',
         'data/geo/counties.json', 'data/bills.json')
KEEP_RELEASES = 10
ASSETS = 'assets'
PAGE_REFERENCES = ('./src/styles.css', './src/app.js')


def versioned_assets(bundle: dict[str, bytes]) -> tuple[str, dict[str, bytes]]:
    """Copy src/ to assets/<digest>/ and point index.html there, so the copy can be cached forever.

    The digest covers every module, so changing any import changes the folder; imports stay relative."""
    sources = sorted(name for name in bundle if name.startswith('src/'))
    digest = hashlib.sha256(b''.join(name.encode() + b'\0' + bundle[name] + b'\0' for name in sources)).hexdigest()[:16]
    files = {f'{ASSETS}/{digest}/{name[len("src/"):]}': bundle[name] for name in sources}
    index = bundle['index.html']
    for reference in PAGE_REFERENCES:
        quoted = f'"{reference}"'.encode()
        if index.count(quoted) != 1:
            raise ValueError('index.html must reference ' + reference + ' exactly once')
        index = index.replace(quoted, f'"./{ASSETS}/{digest}/{reference[len("./src/"):]}"'.encode())
    files['index.html'] = index
    return digest, files


def carry_previous_assets(current: Path, staging: Path, digest: str) -> None:
    # A page loaded from the previous release may still be fetching its assets when current switches.
    try:
        index = (current / 'index.html').read_text(encoding='utf-8')
    except OSError:
        return
    match = re.search(r'\./' + ASSETS + r'/([0-9a-f]{16})/app\.js', index)
    if match and match.group(1) != digest and (current / ASSETS / match.group(1)).is_dir():
        shutil.copytree(current / ASSETS / match.group(1), staging / ASSETS / match.group(1))


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
        digest, versioned = versioned_assets(bundle)
        bundle.update(versioned)
        release.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix='.staging-', dir=release.parent))
        try:
            staging.chmod(0o755)
            for name, content in bundle.items():
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o644)
            carry_previous_assets(current, staging, digest)
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
