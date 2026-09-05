#!/usr/bin/env bash
# Applies the reference solution over the workspace.
set -euo pipefail

WORKSPACE="${WORKSPACE:-/app/event-feed}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cp -R "${HERE}/files/src/." "${WORKSPACE}/src/"

echo "reference solution applied to ${WORKSPACE}"
