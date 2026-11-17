#!/bin/sh
# Install the share card drawer's npm packages (satori, @resvg/resvg-wasm, fonts) for one commit's package-lock.json,
# on the VPS, as root. Run it once whenever package-lock.json changes, before that commit reaches main's og run:
#   sudo sh scripts/install_og_deps.sh [commit]        (default: main of the deployer's repository)
# `npm ci` runs in the same pinned node image texas-bill-og.service uses, as texas-bill-atlas, with install scripts
# off; the result goes to /usr/local/lib/texas-bill-atlas/og-deps/<first 16 hex of sha256(package-lock.json)>/,
# root-owned and read-only to the drawer.
set -eu
NODE_IMAGE=node@sha256:0e1754758c2df4cfa3e68d59e2e1b7374bb7fd9ea6328eaaacf15cc934af8202
REPO=/var/lib/texas-bill-atlas/repository.git
ROOT=/usr/local/lib/texas-bill-atlas/og-deps
git_as() { /usr/sbin/runuser -u texas-bill-atlas -- /usr/bin/git --git-dir="$REPO" "$@"; }

commit=$(git_as rev-parse --verify "${1:-main}^{commit}")
work=$(mktemp -d /tmp/og-deps.XXXXXX)
trap 'rm -rf "$work"' EXIT
git_as show "$commit:package.json" > "$work/package.json"
git_as show "$commit:package-lock.json" > "$work/package-lock.json"
hash=$(sha256sum "$work/package-lock.json" | cut -c1-16)
dest="$ROOT/$hash"
if [ -f "$dest/node_modules/satori/package.json" ]; then
    echo "already installed: $dest"
    exit 0
fi
chown -R texas-bill-atlas:texas-bill-atlas "$work"
docker run --rm --user "$(id -u texas-bill-atlas):$(id -g texas-bill-atlas)" -e npm_config_cache=/w/.npm -v "$work:/w" -w /w \
    "$NODE_IMAGE" npm ci --omit=dev --ignore-scripts --no-audit --no-fund
test -f "$work/node_modules/satori/package.json"
mkdir -p "$ROOT"
rm -rf "$dest.tmp"
mkdir "$dest.tmp"
cp -a "$work/node_modules" "$dest.tmp/node_modules"
chown -R root:root "$dest.tmp"
chmod -R a+rX,go-w "$dest.tmp"
mv "$dest.tmp" "$dest"
echo "installed $dest for commit $commit"
