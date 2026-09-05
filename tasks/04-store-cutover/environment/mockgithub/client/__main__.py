import sys

from ..scenario import SERVICE
from . import cli, stdio


def main() -> int:
    words = sys.argv[1:]
    if words[:1] == [SERVICE]:
        words = words[1:]
    if not words:
        return stdio.run(sys.stdin, sys.stdout, sys.stderr)
    return cli.main(words, sys.stdout, sys.stderr)


raise SystemExit(main())
