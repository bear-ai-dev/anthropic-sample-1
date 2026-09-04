#!/usr/bin/env bash
# Apply the reference solution over the workspace.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
target="${1:-/workspace}"

cp -R "$here/files/src/." "$target/src/"
echo "reference solution applied to $target"
