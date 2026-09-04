# Build context: this directory (tasks/03-analytics-stream-reducer/environment).
#
# Everything the run needs is installed here, because there is no network at
# runtime. Two decisions are load-bearing:
#
#   * one dependency tree, owned by root, shared by the workspace and the
#     grader. React must be a single instance: two copies would put the hooks
#     under test and the renderer that drives them in different runtimes, and
#     every render would fail with an invalid-hook error that has nothing to do
#     with the candidate.
#   * held-out material lives in /grade, mode 700 root, so it is unreadable
#     from the workspace the solver edits.
FROM public.ecr.aws/docker/library/node@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

ENV DEBIAN_FRONTEND=noninteractive

# python3 is not a convenience here, it is a prerequisite for the trial existing
# at all. Harbor installs mini-swe-agent into this sandbox, and one step of that
# installer writes the model provider's credentials with a `python3 - <<PY`
# heredoc run as the agent account. node:20-slim ships no interpreter, so that
# step exits 127 during agent setup -- before the first turn, and long before the
# verifier. The trial then raises instead of scoring and nobody writes a reward
# file at all. The oracle preflight installs no agent and never walks this path,
# which is how this image passed its preflight twice while being incapable of a
# single rollout.
#
# The rest is the shared list. Harbor's installer apt-gets ca-certificates,
# curl, git and build-essential itself, but that runs at setup time over the
# network; having them here means an agent's first minute is not spent on a
# download and a slow mirror cannot cost a trial.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git jq procps python3 ripgrep tzdata xz-utils \
    && rm -rf /var/lib/apt/lists/*

# /logs/verifier holds the verdict and the deliverable snapshot, so the account
# being graded must not be able to read it -- the agent must get
# `Permission denied`, not merely an absent file. It was
# agent-owned here for one reason: nothing else created it, and a verifier that
# cannot create its own log directory writes no reward at all. Root creating it
# 700 answers both, because the verifier runs as root; `tests/test.sh` re-asserts
# the mode at run time so a directory the platform recreates cannot come back
# world-readable. /logs itself stays traversable: Harbor puts the agent's own
# logs beside this.
RUN useradd --create-home --uid 1001 agent \
    && mkdir -p /deps /workspace /grade /logs/verifier \
    && chown root:root /logs /logs/verifier \
    && chmod 755 /logs \
    && chmod 700 /logs/verifier

# Assert the agent account can run what agent setup will ask of it, as that
# account rather than as root. The absence of any one of these is invisible to
# every other check: the image builds, the oracle scores 1.0, the untouched
# workspace scores 0.0, and every rollout raises during setup. A missing
# interpreter should cost a build, not a run.
RUN su agent -s /bin/bash -c '\
      set -eu; \
      for tool in python3 node npm bash tar curl git; do \
        command -v "$tool" >/dev/null || { echo "agent setup needs $tool" >&2; exit 1; }; \
      done; \
      python3 -c "import os, pathlib; pathlib.Path(os.environ[\"HOME\"], \".probe\").write_text(\"ok\")"; \
      rm -f "$HOME/.probe"'

COPY --chown=root:root mocklinear/ /opt/mocklinear/mocklinear/
RUN chmod -R a+rX /opt/mocklinear \
    && find /opt/mocklinear -name '__pycache__' -prune -exec rm -rf {} + \
    && install -m 0755 -o root -g root /opt/mocklinear/mocklinear/bin/mocklinear /usr/local/bin/mocklinear \
    && ln -s /usr/local/bin/mocklinear /usr/local/bin/linear
RUN install -d -m 0755 -o root -g root /opt/linear-sandbox
COPY --chown=root:root --chmod=0444 sandbox/linear/public.json /opt/linear-sandbox/public.json
COPY --chown=root:root --chmod=0400 sandbox/linear/holdout.json /tmp/linear-holdout.json
RUN PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/mocklinear python3 -m mocklinear.check \
      /opt/linear-sandbox/public.json /tmp/linear-holdout.json \
    && rm /tmp/linear-holdout.json

# Dependencies first: this layer is the expensive one and only the manifest
# invalidates it.
COPY workspace/package.json /deps/package.json
RUN cd /deps \
    && npm install --no-audit --no-fund --loglevel=error \
    && npm cache clean --force \
    && rm -rf /root/.npm /tmp/*

COPY workspace/ /workspace/
RUN rm -rf /workspace/node_modules \
    && chown -R agent:agent /workspace \
    && ln -s /deps/node_modules /workspace/node_modules

COPY verifier-data/ /grade/
RUN ln -s /deps/node_modules /grade/node_modules \
    && node /grade/manifest.mjs /workspace/src /grade/pristine-manifest.json \
    && tar -C /workspace -cf /pristine-src.tar src \
    && chown -R root:root /grade /pristine-src.tar \
    && chmod 700 /grade \
    && chmod 600 /pristine-src.tar

ENV VERIFY_WORKSPACE=/workspace \
    VERIFY_GRADE_DIR=/grade \
    VERIFY_OUT_DIR=/tmp/verify-out \
    MOCKLINEAR_URL=http://127.0.0.1:4570 \
    TZ=UTC \
    LANG=C.UTF-8 \
    CI=1

WORKDIR /workspace
COPY task-init.sh /usr/local/bin/task-init.sh
RUN chmod 0755 /usr/local/bin/task-init.sh
USER root
ENTRYPOINT ["/usr/local/bin/task-init.sh"]
CMD ["sleep", "infinity"]
