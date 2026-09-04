#!/bin/bash
# Reference solution.
#
# Applied to a pristine workspace it produces a submission the verifier scores at
# full reward. Ten new files and one modified one; `files/` mirrors the tree, so
# what it changes is legible by looking at it.
#
#   solve.sh [app-dir]        default /app, or $APP_DIR
set -euo pipefail

APP_DIR="${1:-${APP_DIR:-/app}}"
HERE="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$APP_DIR/src/intake" ]; then
    echo "no workspace at $APP_DIR" >&2
    exit 1
fi

cd "$HERE/files"
while IFS= read -r relative; do
    target="$APP_DIR/${relative#./}"
    mkdir -p "$(dirname "$target")"
    cp "$relative" "$target"
    echo "  $relative"
done < <(find . -type f | sort)

echo "reference solution applied to $APP_DIR"
