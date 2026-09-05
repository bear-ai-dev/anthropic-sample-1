# Keeps a pty usable when a large file arrives as one pasted heredoc.
#
# The failure this avoids: a paste of a few hundred lines wedges a terminal
# partway through, and everything after it is lost.

# No line-length limit on what the terminal will accept.
if [ -t 0 ]; then
    stty -ixon 2>/dev/null || true
    stty raw -echo 2>/dev/null && stty -raw echo 2>/dev/null || true
fi

# Bracketed paste off: the shell should not try to be clever about a heredoc.
#
# Only when stdout is a terminal. This file is sourced from /etc/bash.bashrc, so
# it runs for every non-interactive `bash -c` too, and an unconditional printf
# here puts an escape sequence at the front of the FIRST LINE of every command's
# output. Harness code that reads a marker off a line -- `BASELINE_SHA=`,
# `GIT_BIN=`, any `startswith` -- then sees the escape bytes instead and reports
# the marker as missing, with exit code 0 and output that looks fine in a log.
#
# The failure is reported as an exception against a task whose own grader is
# working, plus a silent degradation where staging announces "using git at
# <unknown>" and carries on.
#
# The check, which takes a second and is why `xxd` is in the image:
#
#     bash -lc 'echo MARKER' | xxd | head
#
# The first byte of the first line must be `M`. Anything before it is this
# file's fault and is in the output of every command in the container.
if [ -t 1 ]; then
    printf '\033[?2004l' 2>/dev/null || true
fi

export HISTFILE=/dev/null
export PAGER=cat
export MANPAGER=cat
export GIT_PAGER=cat
export LESS=FRX
export PYTHONDONTWRITEBYTECODE=1
export NPM_CONFIG_FUND=false
export NPM_CONFIG_AUDIT=false
export NPM_CONFIG_UPDATE_NOTIFIER=false
