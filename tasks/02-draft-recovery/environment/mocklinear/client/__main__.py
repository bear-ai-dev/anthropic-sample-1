import sys

from . import dispatch

raise SystemExit(dispatch(sys.argv[1:], sys.stdin, sys.stdout, sys.stderr))
