# Single offline container: Gel 7.1 (with the schema already migrated), Redis,
# and a Go toolchain with a warm module cache. Nothing reaches the network at
# runtime; every download happens here at build time.

# ---------------------------------------------------------------- module cache
FROM public.ecr.aws/docker/library/golang@sha256:1a6d4452c65dea36aac2e2d606b01b4a029ec90cc1ae53890540ce6173ea77ac AS gomod
WORKDIR /src
COPY workspace/go.mod workspace/go.sum ./
RUN go mod download

# ---------------------------------------------------------------------- runtime
# Gel, from this account's ECR rather than Docker Hub, pinned by digest. Hub
# rate-limits anonymous pulls per egress address and CodeBuild's addresses are
# shared, so pulling from Hub fails with a 429 at unpredictable times, and
# several of these tasks start from this image, making them a heavy user of a
# budget they do not control. The digest is the same image Hub served, copied once.
# Pinned rather than tagged so two runs of this task cannot get different
# databases.
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
# /solution root-owned, and mode 700 root:root protects nothing from root.
RUN useradd --create-home --shell /bin/bash agent

# Go toolchain plus the warmed module cache. The cache is copied straight to the
# solver's account rather than chowned afterwards -- a `chown -R` over a
# gigabyte of module cache writes the whole thing again into a new layer.
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
# present: a cache warmed as root into a directory the solver cannot write is a
# cache every build ignores, so every build starts cold and the whole warming
# step buys nothing. /var/log/task is where the service and the smoke check
# write, so it belongs to the same account.
RUN install -d -m 0755 -o agent -g agent /go/cache /go/bin /var/log/task

# Bake the migrated data directory into the image. /var/lib/gel/data is a
# declared VOLUME, so writes there during build are discarded; use /opt/geldata.
# Applying all 94 migrations takes ~160s here so that runtime startup is ~5s.
COPY workspace/gel/dbschema /dbschema
ENV GEL_SERVER_DATADIR=/opt/geldata \
    GEL_SERVER_SECURITY=insecure_dev_mode \
    GEL_SERVER_PASSWORD=dev \
    GEL_SERVER_TLS_CERT_MODE=generate_self_signed \
    GEL_DOCKER_APPLY_MIGRATIONS=always \
    GEL_DOCKER_BOOTSTRAP_TIMEOUT_SEC=900
RUN set -eu; \
    mkdir -p /opt/geldata; \
    chown -R gel:gel /opt/geldata; \
    GEL_SERVER_BOOTSTRAP_ONLY=1 docker-entrypoint.sh server; \
    chown -R gel:gel /opt/geldata

# Connection settings used by the Go service and by the harness.
ENV GEL_DSN=gel://admin:dev@localhost:5656/main \
    GEL_CLIENT_TLS_SECURITY=insecure \
    REDIS_ENDPOINT=localhost:6379 \
    SKIP_AWS_SECRETS=true \
    IS_TEST=true \
    ABLY_SECRET= \
    PORT=3000

# A login shell reads /etc/profile, which rebuilds PATH from scratch and drops
# everything the ENV blocks above set; `su - agent` additionally starts with a
# cleared environment. So a solver in a login shell would find no Go toolchain
# and no database settings, while every check we run -- root, absolute path,
# non-interactive -- would keep passing. Same values, stated a second time in
# the one place a login shell will read them.
RUN printf '%s\n' \
      'export PATH=/usr/local/go/bin:/go/bin:$PATH' \
      'export GOPATH=/go GOMODCACHE=/go/pkg/mod GOCACHE=/go/cache' \
      'export GOFLAGS=-mod=mod GOTOOLCHAIN=local GOPROXY=off' \
      'export GEL_DSN=gel://admin:dev@localhost:5656/main' \
      'export GEL_CLIENT_TLS_SECURITY=insecure' \
      'export REDIS_ENDPOINT=localhost:6379' \
      'export SKIP_AWS_SECRETS=true IS_TEST=true ABLY_SECRET= PORT=3000' \
    > /etc/profile.d/10-task.sh \
 && chmod 0644 /etc/profile.d/10-task.sh

# Where the held-out material arrives. The harness mounts tests/ at /tests and
# the oracle at /solution when they are needed, and the reward goes to
# /logs/verifier; none of the three is in this image. They are created anyway,
# root-owned and unreadable, because "no such file" and "permission denied" read
# identically to a solver and very differently to an audit -- and because
# whoever creates the directory sets its mode, so if the harness gets there
# first with a default 0755 the boundary would depend on nobody having looked.
RUN install -d -m 0700 -o root -g root /tests /solution \
 && install -d -m 0755 -o root -g root /logs \
 && install -d -m 0700 -o root -g root /logs/verifier

# Scripts that start the stack and load the fixture. Nothing graded lives here:
# the independent model and the grader are injected by the verifier, so this
# stays readable and the solver can drive the same database the grader will.
COPY harness /opt/harness
RUN chmod +x /opt/harness/*.sh

# The Linear workspace the box serves for context. Readable, not writable: it
# stands in for Linear, it is not part of the deliverable.
COPY --chown=root:root mocklinear/ /opt/mocklinear/mocklinear/
RUN chmod -R a+rX /opt/mocklinear && \
    find /opt/mocklinear -name '__pycache__' -prune -exec rm -rf {} + && \
    install -m 0755 -o root -g root /opt/mocklinear/mocklinear/bin/mocklinear /usr/local/bin/mocklinear && \
    ln -s /usr/local/bin/mocklinear /usr/local/bin/linear
RUN install -d -m 0755 -o root -g root /opt/linear-sandbox
COPY --chown=root:root --chmod=0444 sandbox/linear/ /opt/linear-sandbox/
RUN PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/mocklinear python3 -m mocklinear.check /opt/linear-sandbox/public.json
ENV MOCKLINEAR_URL=http://127.0.0.1:4570

# The workspace the solver edits, owned by the account that edits it.
COPY --chown=agent:agent workspace /workspace
WORKDIR /workspace
RUN chmod +x /workspace/scripts/svc /workspace/scripts/smoke-scan

# Warm the Go build cache and prove the tree compiles offline, with the same
# flags the harness uses so the cache it warms is the one the grader hits. Warmed
# AS THE SOLVER, so the cache entries belong to the account that will be reusing
# them; warming as root into a cache the agent cannot write leaves every trial
# compiling the standard library again on its first build.
# HOME is set explicitly: a `USER` instruction does not set it, and the Go
# command needs a home to resolve its env file even when GOCACHE is given.
USER agent
RUN set -eu; \
    export HOME=/home/agent; \
    cd /workspace; \
    go build -p 2 -tags timetzdata -ldflags='-s -w' -o /tmp/warm ./cmd/main; \
    rm -f /tmp/warm
USER root

# A pristine copy so the harness can restore between candidates. Taken after the
# warm build and outside it, because the tar must be root-owned while the tree
# inside it keeps the solver's ownership.
RUN tar -C / -czf /opt/workspace-pristine.tar.gz workspace

ENTRYPOINT ["/opt/harness/entrypoint.sh"]
CMD ["sleep", "infinity"]
