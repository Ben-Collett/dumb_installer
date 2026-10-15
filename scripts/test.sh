#!/usr/bin/env bash
# Run the dumb_installer test suite.
#
# The sandboxed tests each build their own bubblewrap sandbox (see
# tests/conftest.py), so this script does not wrap the suite in another one --
# that would just nest namespaces and break the host-path binds the inner
# sandboxes rely on. Its only jobs are to give pytest a writable scratch area
# and to make the missing-bwrap case obvious rather than mysterious.
#
#   ./scripts/test.sh
#   ./scripts/test.sh -k install
#   ./scripts/test.sh -m "not sandbox"     # fast tests, no bwrap needed
#
# Any extra arguments are forwarded to pytest.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v bwrap >/dev/null 2>&1; then
    cat >&2 <<'MSG'
bwrap not found: the sandboxed tests will be skipped.

On Arch/EndeavourOS:  sudo pacman -S bubblewrap
On Debian/Ubuntu:     sudo apt install bubblewrap

The remaining tests still run; they do not touch any system path.
MSG
fi

# Keep pytest's scratch space out of the repo so the working tree stays clean.
PYTEST_TMP="$(mktemp -d -t dumb-installer-tests-XXXXXX)"
trap 'rm -rf "$PYTEST_TMP"' EXIT

exec python3 -m pytest \
    -p no:cacheprovider \
    --basetemp="$PYTEST_TMP" \
    -c "$REPO_ROOT/pyproject.toml" \
    "$@" \
    "$REPO_ROOT/tests"
