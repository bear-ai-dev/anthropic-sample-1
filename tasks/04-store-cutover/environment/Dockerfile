# The ledger's box: the destination database, the coordination keyspace, the
# storage service in front of them, and the Go toolchain to build the service.
# Nothing here reaches a network at run time.
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

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git jq patch procps psmisc python3 redis-server \
        redis-tools ripgrep sqlite3 sudo tzdata vim-tiny && \
    rm -rf /var/lib/apt/lists/*

ENV TZ=Etc/UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# The toolchain comes from the official image so it matches the host
# architecture without a download step here.
COPY --from=public.ecr.aws/docker/library/golang@sha256:3b4a11519ad929d1e1d261a12cff056f0c85b735253d7d861346b9c6f8b36437 /usr/local/go /usr/local/go
ENV PATH=/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GOTOOLCHAIN=local \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --shell /bin/bash agent

# A login shell takes its PATH from /etc/profile, which clobbers the image's
# PATH and knows nothing about the Go toolchain: `bash -lc 'go build'` fails with
# "go: command not found" while the identical command in a non-login shell works.
# Nothing graded goes through a login shell -- the verifier builds with an
# explicit `env -i PATH=...` -- but a solver's shell may, and a toolchain that
# appears or disappears depending on how the shell was opened is a tax the grader
# never sees.
#
# Exports and nothing else. A profile script that writes so much as a newline to
# stdout corrupts the first command the agent runs and reads as a broken task;
# `su agent -lc 'echo MARKER'` is
# checked byte for byte against it.
RUN printf '%s\n' \
    'PATH=/usr/local/go/bin:$PATH' \
    ': "${GOPATH:=/go}"; : "${GOMODCACHE:=/go/pkg/mod}"' \
    ': "${GOCACHE:=$HOME/.cache/go-build}"; : "${GOTOOLCHAIN:=local}"' \
    ': "${GOFLAGS:=-mod=mod}"; : "${GOPROXY:=off}"' \
    'export PATH GOPATH GOMODCACHE GOCACHE GOTOOLCHAIN GOFLAGS GOPROXY' \
    > /etc/profile.d/10-go-toolchain.sh && \
    chmod 0644 /etc/profile.d/10-go-toolchain.sh

# The storage service. It stands in for a managed store, it is not part of the
# deliverable, and the account that owns /app cannot change it.
COPY --chown=root:root storesvc/ /opt/storesvc/
RUN cd /opt/storesvc && \
    GOFLAGS=-mod=mod go build -o /usr/local/bin/storesvc . && \
    chmod 0755 /usr/local/bin/storesvc && \
    go clean -cache -modcache && \
    rm -rf /opt/storesvc

# The destination schema, as a Gel project the box applies at start-up.
RUN install -d -m 0755 /opt/ledger/gelproj/dbschema
COPY --chown=root:root schema/default.gel /opt/ledger/gelproj/dbschema/default.gel
RUN printf '[instance]\nserver-version = "7.1"\n' > /opt/ledger/gelproj/gel.toml && \
    chmod -R a+rX /opt/ledger/gelproj && chmod -R u+w /opt/ledger/gelproj

# Two datasets from one generator: the one the box develops against, and the
# one a graded run uses. Same shape, no values in common, and each in its own
# member id range so the two share no identifier at all. The archived cutover
# in the workspace was recorded from a third, in a third range. The graded
# dataset and the generator that made it are readable by root alone.
COPY --chown=root:root fixtures/build_fixture.py /opt/ledger/fixtures/build_fixture.py
RUN install -d -m 0755 /opt/ledger/fixtures/dev && \
    python3 /opt/ledger/fixtures/build_fixture.py \
        --seed 3234567891 --members 300 --entries 1500 --base-epoch 1742000000 \
        --out-db /opt/ledger/fixtures/dev/legacy.db \
        --out-log /opt/ledger/fixtures/dev/truth.jsonl \
        --out-summary /opt/ledger/fixtures/dev/summary.json && \
    chmod 0644 /opt/ledger/fixtures/dev/legacy.db && \
    rm -f /opt/ledger/fixtures/dev/truth.jsonl

RUN install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/verifier && \
    install -d -m 0700 -o root -g root /var/lib/task-data/verifier/graded && \
    python3 /opt/ledger/fixtures/build_fixture.py \
        --seed 987654321 --members 340 --entries 1720 --base-epoch 1745000000 \
        --first-member 400001 \
        --out-db /var/lib/task-data/verifier/graded/legacy.db \
        --out-log /var/lib/task-data/verifier/graded/truth.jsonl \
        --out-summary /var/lib/task-data/verifier/graded/summary.json && \
    rm -f /opt/ledger/fixtures/build_fixture.py && \
    chmod -R go-rwx /var/lib/task-data

# Verifier-only material: the independent model of the specification, the fault
# plans a graded run installs, and the driver. The agent account sees an opaque
# parent directory and nothing inside it.
COPY --chown=root:root --chmod=600 verifier-data/ /var/lib/task-data/verifier/
RUN chmod -R u+rwX,go-rwx /var/lib/task-data/verifier

RUN install -d -o agent -g agent /app /app/data
WORKDIR /app
COPY --chown=agent:agent workspace/ /app/

# Warm the module cache and the build cache as the account that will be
# building, so a build works with no network at all.
ENV GOPATH=/go GOMODCACHE=/go/pkg/mod GOCACHE=/home/agent/.cache/go-build
RUN install -d -o agent -g agent /go /go/pkg /go/pkg/mod
USER agent
RUN cd /app && go mod download && go build ./... && go vet ./... && rm -f /app/membershipd /app/membershipledger
USER root
ENV GOFLAGS=-mod=mod GOPROXY=off

# A root-only copy of the starting sources, so a finished run can be diffed
# against what the box began with, and so a graded run can put the workspace
# back the way it was.
RUN install -d -m 0700 -o root -g root /var/lib/task-data/pristine_app && \
    tar -C /app -cf - . | tar -C /var/lib/task-data/pristine_app -xf - && \
    chown -R root:root /var/lib/task-data/pristine_app && \
    chmod -R go-rwx /var/lib/task-data/pristine_app

COPY --chown=root:root task-init.sh /usr/local/bin/task-init.sh
RUN chmod 0755 /usr/local/bin/task-init.sh

# The GitHub workspace the box serves for context. Readable, not writable: it
# stands in for GitHub, it is not part of the deliverable.
COPY --chown=root:root mockgithub/ /opt/mockgithub/mockgithub/
RUN chmod -R a+rX /opt/mockgithub && \
    find /opt/mockgithub -name '__pycache__' -prune -exec rm -rf {} + && \
    install -m 0755 -o root -g root /opt/mockgithub/mockgithub/bin/mockgithub /usr/local/bin/mockgithub && \
    ln -s /usr/local/bin/mockgithub /usr/local/bin/github
RUN install -d -m 0755 -o root -g root /opt/github-sandbox
COPY --chown=root:root --chmod=0444 sandbox/github/ /opt/github-sandbox/
RUN PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/mockgithub python3 -m mockgithub.check /opt/github-sandbox/public.json
ENV MOCKGITHUB_URL=http://127.0.0.1:4570

ENV GEL_DSN=gel://admin:dev@localhost:5656/main \
    GEL_CLIENT_TLS_SECURITY=insecure \
    LEDGER_CONFIG=/app/config/migration.yaml

ENTRYPOINT ["/usr/local/bin/task-init.sh"]
CMD ["--wait"]
