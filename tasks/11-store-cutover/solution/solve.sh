#!/bin/bash
# Apply the reference solution over the workspace and prove it builds.
set -euo pipefail

APP="${APP_DIR:-/app}"
HERE="$(cd "$(dirname "$0")" && pwd)"

cp -a "$HERE/files/." "$APP/"
cd "$APP"
go build ./...
echo "reference solution applied to $APP"
