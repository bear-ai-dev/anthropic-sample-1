# syntax=docker/dockerfile:1
#
# Task 12 - read-model reprocessing.
#
# One container: Gel 7.1 (append log and projections), Redis (query routing and
# rebuild bookkeeping), Node 20 (the service), and a prebuilt Go binary the
# verifier uses to fold the canonical event log. Everything needed at run time is
# installed here, because the container runs with no network.
#
# The build context is this directory, not the task directory: the CLI zips
# `environment/` and builds it as `.`, so every path below is relative to
# `environment/` and nothing outside it can be reached. The grader is not here
# for that reason and for a second one -- it is held-out material, and Harbor
# uploads `tests/` to /tests after the agent has finished.
#
# The shipped image is x86-64, because CodeBuild and the Fargate sandbox both
# are. Building it on an arm64 workstation works but produces a container whose
# redis-server takes SIGSEGV under emulation, so the local matrix builds an
# arm64 variant instead; see .local/12/build-matrix-image.sh.
#
#   docker build -f Dockerfile -t sample-12:v3 environment/

# The toolchain runs on whatever the builder is and emits a binary for whatever
# the image is for. On CodeBuild those are the same thing and this is a no-op;
# on an Apple Silicon workstation it is the difference between compiling and
# not, because the Go compiler under x86-64 emulation dies on `lfstack.push
# invalid packing` -- the runtime packs a pointer and a counter into one word
# and the emulator hands out addresses that will not fit. tzdata is linked into
# the binary, so there is nothing host-specific left to go wrong.
FROM --platform=$BUILDPLATFORM public.ecr.aws/docker/library/golang@sha256:167053a2bb901972bf2c1611f8f52c44d5fe7e762e5cab213708d82c421614db AS model
ARG TARGETOS
ARG TARGETARCH
WORKDIR /src
COPY verifier-data/model/go.mod ./
COPY verifier-data/model/*.go ./
RUN CGO_ENABLED=0 GOOS="${TARGETOS}" GOARCH="${TARGETARCH}" \
    go build -trimpath -o /out/projfold .

# Gel, from this account's ECR rather than Docker Hub, pinned by digest. Hub
# rate-limits anonymous pulls per egress address and CodeBuild's addresses are
# shared, so pulling from Hub fails with a 429 at unpredictable times, and several
# of these tasks start from this image, making them a heavy user of a budget
# it does not control. The digest is the same image Hub served, copied once.
# Pinned rather than tagged so two runs of this task cannot get different
# databases. Re-seed with .local/mirror-base-image.py if it ever goes missing.
# The Gel 7.1 server image (geldata/gel:7.1, amd64), mirrored into
# evaluation/base-images, a repository with no expiry policy. The previous
# mirror lived in specific/envs, whose keep-last-30 lifecycle rule expired it
# once forge builds started landing there hourly.
FROM [REDACTED_PRIVATE_REGISTRY]/evaluation/base-images@sha256:0647f02cd1d62657b1f70b1dac1f312d7d1ba115d9852e7feaff085f2133520c

ARG NODE_VERSION=20.18.1
ENV DEBIAN_FRONTEND=noninteractive

# The stores, and the tools an agent is entitled to find in a working box.
#
# python3 is not a convenience here, it is a prerequisite for the trial existing
# at all: Harbor installs mini-swe-agent into this sandbox and writes the model
# provider's credentials with a `python3 - <<PY` heredoc run as the agent
# account. Without an interpreter that exits 127 during agent setup, before the
# first turn and long before the verifier -- so the trial raises instead of
# scoring, and no reward file is written by anyone. The oracle preflight
# installs no agent and never touches this path, which is why an image can pass
# its preflight and be incapable of a single rollout.
#
# The rest is the shared list. Harbor's installer apt-gets git and
# build-essential itself, but that runs at setup time over the network; having
# them already here means an agent's first minute is not spent on a download,
# and a slow mirror cannot cost a trial.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq patch procps psmisc python3 redis-server \
      redis-tools ripgrep sudo tzdata vim-tiny xz-utils \
 && rm -rf /var/lib/apt/lists/*

# The architecture is asked for rather than assumed. This was pinned to arm64,
# which is the workstation these tasks are written on and neither of the two
# machines that matter: CodeBuild runs aws/codebuild/standard on x86-64 and the
# sandbox is a Fargate X86_64 task, so a run that got this far unpacked a tree
# of aarch64 binaries and fell over on `node --version`.
RUN case "$(dpkg --print-architecture)" in \
      amd64) NODE_ARCH=x64 ;; \
      arm64) NODE_ARCH=arm64 ;; \
      *) echo "no Node build for $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac \
 && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o /tmp/node.txz \
 && tar -xJf /tmp/node.txz -C /usr/local --strip-components=1 \
 && rm /tmp/node.txz \
 && node --version

# The account the solver works as. It exists so that the canonical delivery log
# and the independent model, both of which are baked in below, are out of reach
# of the workspace; see the note in task.toml.
RUN useradd --create-home --shell /bin/bash agent

# What Harbor needs from this image before the agent takes a turn, checked as
# the account that will need it. This is here because the absence of one of
# these is invisible to every check we run: the image builds, the oracle scores
# 1.0, the untouched workspace scores 0.0, and every rollout raises during agent
# setup. A missing interpreter should cost a build, not a run.
RUN su agent -s /bin/bash -c '\
      set -eu; \
      for tool in python3 node npm bash tar curl git; do \
        command -v "$tool" >/dev/null || { echo "agent setup needs $tool" >&2; exit 1; }; \
      done; \
      python3 -c "import os, pathlib; pathlib.Path(os.environ[\"HOME\"], \".probe\").write_text(\"ok\")"; \
      rm -f "$HOME/.probe"'

COPY --chown=root:root mockgithub/ /opt/mockgithub/mockgithub/
RUN chmod -R a+rX /opt/mockgithub \
 && find /opt/mockgithub -name '__pycache__' -prune -exec rm -rf {} + \
 && install -m 0755 -o root -g root /opt/mockgithub/mockgithub/bin/mockgithub /usr/local/bin/mockgithub \
 && ln -s /usr/local/bin/mockgithub /usr/local/bin/github
RUN install -d -m 0755 -o root -g root /opt/github-sandbox
COPY --chown=root:root --chmod=0444 sandbox/github/public.json /opt/github-sandbox/public.json
COPY --chown=root:root --chmod=0400 sandbox/github/holdout.json /tmp/github-holdout.json
RUN PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/mockgithub python3 -m mockgithub.check \
      /opt/github-sandbox/public.json /tmp/github-holdout.json \
 && rm /tmp/github-holdout.json

# ---------------------------------------------------------------- workspace --
WORKDIR /app/event-feed
COPY workspace/event-feed/package.json ./
RUN npm install --no-audit --no-fund --loglevel=error \
 && npm cache clean --force

COPY --chown=agent:agent workspace/event-feed/ ./

# The `gel` npm package installs a CLI shim of the same name that downloads the
# real binary on first use. Offline that is a hang followed by a DNS failure, so
# it must never shadow /usr/bin/gel.
RUN rm -f node_modules/.bin/gel node_modules/.bin/edgedb \
 && test -x /usr/bin/gel

RUN chown -R agent:agent /app

# --------------------------------------------------------------- verifier ----
# Held out from the workspace: root-owned, mode 0700, nothing under /app. This
# is the canonical delivery log the model folds, the script of live deliveries a
# graded run replays, and the model's own sources -- all of which state the
# answers the rules are judged against, which is why the solver is not root.
#
# The grader that reads them is deliberately absent. It arrives at /tests when
# the verifier runs, after the agent has stopped.
COPY verifier-data/ /opt/verifier/
COPY --from=model /out/projfold /opt/verifier/bin/projfold
RUN chmod -R 0700 /opt/verifier \
 && chmod 0755 /opt/verifier/bin/projfold \
 && chown -R root:root /opt/verifier

# The model derives New York dates from the daylight-saving rule and checks that
# against tzdata. Run here rather than in the builder stage: the binary is built
# for this image's architecture, not the builder's, so this is the first place
# it can execute. A disagreement means the verifier would grade against a
# bucketing it cannot justify, and the build stops instead.
RUN /opt/verifier/bin/projfold check

# A pristine copy of the workspace, used to restore between matrix candidates.
# node_modules is excluded so restoring is cheap.
RUN tar -C /app -cf /opt/pristine-workspace.tar --exclude=node_modules event-feed \
 && chmod 0600 /opt/pristine-workspace.tar

# Gel sizes its compiler pool from the host's CPU count, which on a shared box
# means ten worker processes and well over a gigabyte of resident memory for a
# workload that compiles a handful of distinct queries. Two is ample and keeps
# the server off the out-of-memory killer's shortlist.
ENV GEL_SERVER_COMPILER_POOL_SIZE=2 \
    GEL_SERVER_SECURITY=insecure_dev_mode \
    GEL_SERVER_PASSWORD=dev \
    GEL_SERVER_TLS_CERT_MODE=generate_self_signed \
    GEL_DSN=gel://admin:dev@localhost:5656/main \
    GEL_CLIENT_TLS_SECURITY=insecure \
    REDIS_URL=redis://127.0.0.1:6379 \
    MOCKGITHUB_URL=http://127.0.0.1:4570 \
    PORT=8080 \
    IS_TEST=true \
    NODE_ENV=production

COPY task-init.sh /usr/local/bin/task-init.sh
RUN chmod 0755 /usr/local/bin/task-init.sh

WORKDIR /app/event-feed
ENTRYPOINT ["/usr/local/bin/task-init.sh"]
CMD ["--wait"]
