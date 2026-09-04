#!/bin/bash
# Reference solution: lay the oracle tree over the workspace.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${WORKSPACE:-/workspace}"

# Harbor may invoke this through a login shell, which rebuilds PATH from
# /etc/profile and loses the image's ENV. Name the toolchain rather than trust
# the ambient environment to still have it.
export PATH="/usr/local/go/bin:/go/bin:$PATH"
export GOPATH="${GOPATH:-/go}" GOFLAGS="${GOFLAGS:--mod=mod}"
export GOCACHE="${GOCACHE:-/go/cache}" GOMODCACHE="${GOMODCACHE:-/go/pkg/mod}"
export GOTOOLCHAIN=local GOPROXY=off

cp -a "$HERE/files/." "$WORKSPACE/"

# Same flags the harness uses, so this warms the cache the grader will hit
# instead of populating a second one.
cd "$WORKSPACE"
go build -p "${GO_BUILD_P:-2}" -tags timetzdata -ldflags='-s -w' \
   -o bin/ExampleCo-backend ./cmd/main
echo "[solve] oracle applied and building"
