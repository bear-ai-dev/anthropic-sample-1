# Single offline container: Gel 7.1 with the schema already migrated, Redis, and
# a Go toolchain with a warm module cache. Nothing reaches the network at
# runtime; every download happens here, at build time.

# ---------------------------------------------------------------- module cache
FROM public.ecr.aws/docker/library/golang@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS gomod
WORKDIR /src
COPY workspace/go.mod workspace/go.sum ./
RUN go mod download

# ---------------------------------------------------------------------- runtime
# Gel, from this account's ECR rather than Docker Hub, pinned by digest. Hub
# rate-limits anonymous pulls per egress address and CodeBuild's addresses are
# shared, so a Hub pull fails with a 429 at unpredictable times. The digest is
# the same image Hub served, copied once. Pinned rather than tagged so that two
# runs of this task cannot get different databases.
# The Gel 7.1 server image (geldata/gel:7.1, amd64), mirrored into
# evaluation/base-images, a repository with no expiry policy. The previous
# mirror lived in specific/envs, whose keep-last-30 lifecycle rule expired it
# once forge builds started landing there hourly.
FROM [REDACTED_PRIVATE_REGISTRY]/evaluation/base-images@sha256:0647f02cd1d62657b1f70b1dac1f312d7d1ba115d9852e7feaff085f2133520c

# postgis is required by the schema. The Gel entrypoint would apt-get it on
# first boot, which cannot work offline, so it is installed here instead.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      gel-server-7-ext-postgis \
      redis-server curl jq procps python3 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# The account the solver works in. It is not root, and that is the whole point:
# the grader, the independent model and the oracle arrive at /tests and
# /solution root-owned, and mode 700 root:root protects nothing from root. This
# task ran its solver as root for two rounds on the argument that nothing held
# out is baked into the image, which is true and is not the same claim: the
# holdout is not in the image, but it is mounted into the container the solver
# is still sitting in when grading starts.
RUN useradd --create-home --shell /bin/bash agent

# Go toolchain plus the warmed module cache. Both `FROM` and this `COPY --from`
# name the ECR mirror by digest for the same reason. The module cache is copied
# straight to the solver's account rather than chowned afterwards -- `chown -R`
# over a gigabyte of module cache rewrites the whole thing into a new layer.
COPY --from=public.ecr.aws/docker/library/golang@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac /usr/local/go /usr/local/go
COPY --from=gomod --chown=agent:agent /go/pkg/mod /go/pkg/mod
ENV GOPATH=/go \
    GOMODCACHE=/go/pkg/mod \
    GOCACHE=/go/cache \
    GOFLAGS=-mod=mod \
    GOTOOLCHAIN=local \
    GOPROXY=off \
    PATH=/usr/local/go/bin:/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# The build cache has to be WRITABLE by the account that builds, not merely
# present. A cache warmed as root into a directory the solver cannot write is a
# cache every one of the solver's builds silently declines to use, so every
# build starts cold and the warming step below buys nothing at all -- which is
# the exact defect this task spent a round measuring. /var/log/task is where the
# service and smoke.sh write, so it belongs to the same account.
RUN install -d -m 0755 -o agent -g agent /go/cache /go/bin /var/log/task

# Bake the migrated data directory into the image. /var/lib/gel/data is a
# declared VOLUME, so writes there during build are discarded; use /opt/geldata.
# Applying all 94 migrations takes a couple of minutes on an idle host so that
# runtime startup is a few seconds.
#
# GEL_DOCKER_BOOTSTRAP_TIMEOUT_SEC is well above what that needs, because the
# entrypoint enforces it by sending itself SIGTERM and the failure that produces
# is a stack of CancelledError with "Could not complete instance bootstrap" at
# the bottom -- it reads like a broken schema rather than a clock running out. On
# a contended builder the standard-library initialisation alone has taken twenty
# minutes, so the ceiling is set for the slow case and costs nothing in the fast
# one.
#
# Migration 00094 is this task's own: it adds repeat_config.timezone. The zone a
# series recurs in has to be stored, because every date in a series is a local
# calendar date in that zone and an occurrence list cannot be reconstructed from
# instants alone. It was authored by Gel rather than by hand -- the migration
# name is a hash over the parent and the statements, and the server refuses a
# name it did not compute.
COPY workspace/gel/dbschema /dbschema
ENV GEL_SERVER_DATADIR=/opt/geldata \
    GEL_SERVER_SECURITY=insecure_dev_mode \
    GEL_SERVER_PASSWORD=dev \
    GEL_SERVER_TLS_CERT_MODE=generate_self_signed \
    GEL_DOCKER_APPLY_MIGRATIONS=always \
    GEL_DOCKER_BOOTSTRAP_TIMEOUT_SEC=5400
RUN set -eu; \
    mkdir -p /opt/geldata; \
    chown -R gel:gel /opt/geldata; \
    GEL_SERVER_BOOTSTRAP_ONLY=1 docker-entrypoint.sh server; \
    chown -R gel:gel /opt/geldata

# Connection settings used by the Go service and by the harness. TZ is left
# unset on purpose: a solver who reads the process zone instead of the series
# zone should not be rescued by the container happening to run in one of the
# zones the fixture uses.
ENV GEL_DSN=gel://admin:dev@localhost:5656/main \
    GEL_CLIENT_TLS_SECURITY=insecure \
    REDIS_ENDPOINT=localhost:6379 \
    MOCKLINEAR_URL=http://127.0.0.1:4570 \
    SKIP_AWS_SECRETS=true \
    IS_TEST=true \
    ABLY_SECRET= \
    PORT=3000 \
    TZ=UTC

# Scripts that start the stack and load the fixture. Nothing graded lives here:
# the independent model and the grader are injected by the verifier, so this
# stays readable and the solver can drive the same database the grader will.
COPY harness /opt/harness
RUN chmod +x /opt/harness/*.sh

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

# A login shell sources /etc/profile, which rebuilds PATH from scratch and drops
# every ENV block above; `su - agent` starts from a cleared environment on top of
# that. So a solver in a login shell would find no Go toolchain and no database
# settings while every check made from a root shell with an absolute path kept
# passing. Same values, stated a second time in the one place a login shell
# reads. TZ is restated too, so that what the solver's shell sees and what
# test.sh pins are the same zone and a candidate cannot be accidentally right in
# one of them.
RUN printf '%s\n' \
      'export PATH=/usr/local/go/bin:/go/bin:$PATH' \
      'export GOPATH=/go GOMODCACHE=/go/pkg/mod GOCACHE=/go/cache' \
      'export GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off' \
      'export GEL_DSN=gel://admin:dev@localhost:5656/main' \
      'export GEL_CLIENT_TLS_SECURITY=insecure' \
      'export REDIS_ENDPOINT=localhost:6379' \
      'export MOCKLINEAR_URL=http://127.0.0.1:4570' \
      'export SKIP_AWS_SECRETS=true IS_TEST=true ABLY_SECRET= PORT=3000' \
      'export TZ=UTC' \
    > /etc/profile.d/10-task.sh \
 && chmod 0644 /etc/profile.d/10-task.sh

# The independent recurrence model is deliberately NOT copied here. It states
# the expected answer for every graded rule, and it lives under tests/, which the
# harness uploads and mounts only when grading runs.
#
# Where that held-out material arrives is created here anyway, root-owned and
# unreadable. Two reasons. Whoever creates a directory sets its mode, so if the
# harness gets there first with a default 0755 the boundary depends on nobody
# having looked; and "no such file" and "permission denied" read identically to
# a solver and very differently to an audit.
RUN install -d -m 0700 -o root -g root /tests /solution \
 && install -d -m 0755 -o root -g root /logs \
 && install -d -m 0700 -o root -g root /logs/verifier

# The workspace the solver edits, owned by the account that edits it.
COPY --chown=agent:agent workspace /workspace
WORKDIR /workspace

# Warm the Go build cache and prove the tree compiles offline.
#
# The first line is the grader's own build, with the grader's own flags, so the
# cache it warms is the one the grader hits. It is also the only strict one:
# a tree that does not compile here is a broken image, not a wrong answer.
#
# The rest are the builds a solver types, and they are not the same builds.
# Warming only `./cmd/main` warms only what that one binary imports, so the
# first `go build ./...` in the sandbox compiled some nine hundred packages
# from cold: 67s on an idle four-core box and ten minutes on a busy one. The
# command timeout was about thirty seconds when both probe trials hit this, and
# both lost the build to it with rc=-1 and spent the rest of the run
# backgrounding builds behind nohup and polling them with sleep. The timeout is
# 300s now, so that particular death is off the table, but a solver waiting a
# minute an iteration has lost the trial the slower way. Warmed, the same
# command is 19s idle.
#
# Both tag sets, because `-tags` is part of every package's action id: a cache
# warmed with `timetzdata` is a miss for the plain `go build ./...` the tree
# invites, and the other way round. `go vet` keeps its analysis results in the
# same cache under its own keys, and a solver checking their work pays 57s for
# `go vet ./internal/v2/...` cold and 21s warm on the same busy host.
#
# What warming cannot buy is the link. Compiling the whole 1002-package graph
# of ./cmd/main out of a warm cache is six seconds; linking the 61MB binary
# afterwards is the rest, and it has to happen again after every edit because
# its inputs changed. Measured here: same edit, `-o /tmp/x` 63s, and with
# `-ldflags='-s -w'` 34s, because most of what the linker is doing is DWARF.
# That is why instruction.md names those flags -- they are the grader's flags,
# they are the flags warmed on the first line, and they halve the one part of
# the loop no cache can remove. A solver who only wants to know whether their
# change compiles should reach for `go build ./internal/v2/...`, which links
# nothing and is 5.6s warm.
#
# `|| true` because `ExampleCo-core/migrate/main` does not build: it is a package
# main with no func main, upstream, and unrelated to anything here. Only the
# strict line above decides whether this image is sound. `-o` is left off on
# purpose -- with several main packages `go build` discards the executables, so
# nothing lands in the tree that the pristine tarball below would capture, and
# it skips the link step that is most of the cost.
#
# All of it runs AS THE SOLVER. Cache entries written by root land in a cache
# the agent cannot add to, and the Go command's response to a cache it cannot
# write is to carry on without one -- quietly, with a correct binary at the end,
# which is why warming as root looks like it worked. HOME is exported by hand:
# a USER instruction does not set it, and the go command wants a home for its
# env file even when GOCACHE is given explicitly.
USER agent
RUN set -eu; \
    export HOME=/home/agent; \
    cd /workspace; \
    go build -p 2 -tags timetzdata -ldflags='-s -w' -o /tmp/warm ./cmd/main; \
    rm -f /tmp/warm; \
    go build -p 2 -tags timetzdata -o /tmp/warm ./cmd/main; \
    rm -f /tmp/warm; \
    go build -p 4 ./... 2>/dev/null || true; \
    go build -p 4 -tags timetzdata ./... 2>/dev/null || true; \
    go vet ./... >/dev/null 2>&1 || true
USER root

# A pristine copy so the harness can restore between candidates. Taken after the
# warm build and outside it, because the tar has to be root-owned while the tree
# inside it keeps the solver's ownership.
RUN tar -C / -czf /opt/workspace-pristine.tar.gz workspace

ENTRYPOINT ["/opt/harness/entrypoint.sh"]
CMD ["sleep", "infinity"]
