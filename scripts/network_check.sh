#!/usr/bin/env bash
# Periodic sanity check against a real remote repository.
#
# The automated suite deliberately uses local file:// repositories so it never
# needs the network (see TESTING_PLAN.md section 6, Phase 7). That cannot
# catch failures which only appear against a real remote: credential prompts,
# real clone sizes, shallow-clone behaviour at depth 1, and whatever a hosting
# provider does that a local bare repo does not.
#
# Run this by hand, now and then. It installs a public repository into a
# throwaway sandbox and updates it once.
#
#   ./scripts/network_check.sh [repo-url]
#
# Default repo: the dumb_installer repository itself.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="${1:-https://github.com/Ben-Collett/dumb_installer}"

if ! command -v bwrap >/dev/null 2>&1; then
    echo "bwrap not found; install bubblewrap to run this check." >&2
    exit 1
fi
if ! command -v git >/dev/null 2>&1; then
    echo "git not found." >&2
    exit 1
fi

ROOT="$(mktemp -d -t dumb-installer-netcheck-XXXXXX)"
trap 'rm -rf "$ROOT"' EXIT

mkdir -p "$ROOT/bin" "$ROOT/lib" "$ROOT/etc" "$ROOT/xdg" "$ROOT/work"

echo "==> installing $URL into a sandbox"
bwrap \
    --ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib \
    --ro-bind /lib64 /lib64 --ro-bind /sbin /sbin \
    --tmpfs /etc \
    --ro-bind /etc/passwd /etc/passwd --ro-bind /etc/group /etc/group \
    --ro-bind /etc/shadow /etc/shadow --ro-bind /etc/ssl /etc/ssl \
    --ro-bind /etc/resolv.conf /etc/resolv.conf --ro-bind /etc/hosts /etc/hosts \
    --bind "$ROOT/etc" /etc/dumb_installer \
    --bind "$ROOT/bin" /usr/local/bin \
    --tmpfs /usr/lib --ro-bind /usr/lib /usr/lib \
    --bind "$ROOT/lib" /usr/lib/dumb_builds \
    --bind "$ROOT/xdg" /xdg_config \
    --ro-bind "$REPO_ROOT" /repo \
    --tmpfs "$ROOT/tmp" \
    --proc /proc --dev /dev --unshare-all --die-with-parent \
    --chdir /repo \
    --setenv PATH /usr/local/bin:/usr/bin:/bin \
    --setenv HOME /etc --setenv XDG_CONFIG_HOME /xdg_config \
    --setenv PYTHONPATH /repo --setenv GIT_TERMINAL_PROMPT 0 \
    /usr/bin/python3 /repo/dumb_installer.py "$URL" || {
        echo "FAIL: install exited non-zero" >&2
        exit 1
    }

if [ -x "$ROOT/bin/din" ]; then
    echo "==> installed wrapper present at \$ROOT/bin/din"
else
    echo "note: no 'din' wrapper found; the repo's executable_name may differ"
fi

echo "==> updating once"
bwrap \
    --ro-bind /usr /usr --ro-bind /bin /bin --ro-bind /lib /lib \
    --ro-bind /lib64 /lib64 --ro-bind /sbin /sbin \
    --tmpfs /etc \
    --ro-bind /etc/passwd /etc/passwd --ro-bind /etc/group /etc/group \
    --ro-bind /etc/shadow /etc/shadow --ro-bind /etc/ssl /etc/ssl \
    --ro-bind /etc/resolv.conf /etc/resolv.conf --ro-bind /etc/hosts /etc/hosts \
    --bind "$ROOT/etc" /etc/dumb_installer \
    --bind "$ROOT/bin" /usr/local/bin \
    --tmpfs /usr/lib --ro-bind /usr/lib /usr/lib \
    --bind "$ROOT/lib" /usr/lib/dumb_builds \
    --bind "$ROOT/xdg" /xdg_config \
    --ro-bind "$REPO_ROOT" /repo \
    --tmpfs "$ROOT/tmp" \
    --proc /proc --dev /dev --unshare-all --die-with-parent \
    --chdir /repo \
    --setenv PATH /usr/local/bin:/usr/bin:/bin \
    --setenv HOME /etc --setenv XDG_CONFIG_HOME /xdg_config \
    --setenv PYTHONPATH /repo --setenv GIT_TERMINAL_PROMPT 0 \
    /usr/bin/python3 /repo/dumb_installer.py --update-all || {
        echo "FAIL: update exited non-zero" >&2
        exit 1
    }

echo "OK: real-network install and update both succeeded"
