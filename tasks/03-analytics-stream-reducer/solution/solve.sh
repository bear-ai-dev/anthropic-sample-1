#!/usr/bin/env bash
# Apply the reference solution over the workspace.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${1:-/workspace}"

cd "$HERE/src"
find . -type f \( -name '*.ts' -o -name '*.tsx' \) -print0 | while IFS= read -r -d '' f; do
    dest="$WORKSPACE/src/${f#./}"
    mkdir -p "$(dirname "$dest")"
    cp "$HERE/src/${f#./}" "$dest"
done

echo "reference solution applied to $WORKSPACE"
