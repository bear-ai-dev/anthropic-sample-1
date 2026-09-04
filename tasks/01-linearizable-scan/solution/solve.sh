#!/bin/bash
# Reference solution: lay the oracle tree over the workspace.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-/workspace}"

cp -a "$HERE/files/." "$WORKSPACE/"

# Same flags the harness uses, so this warms the cache the grader will hit
# instead of populating a second one.
cd "$WORKSPACE"
go build -p "${GO_BUILD_P:-2}" -tags timetzdata -ldflags='-s -w' \
   -o bin/ExampleCo-backend ./cmd/main
echo "[solve] oracle applied and building"
