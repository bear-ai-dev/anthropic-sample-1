# Build context: this directory (tasks/04-draft-recovery/environment).
#
# The CLI zips `environment/` and builds it with `-f Dockerfile .`, so every
# path below is relative to this directory. A path written from the task root
# builds locally and then fails in the real harness.
#
# One dependency tree, installed once into /deps and owned by root. Both the
# workspace the agent edits and the grader that drives it point at it, because
# two copies of React put the hooks under test and the renderer driving them in
# different runtimes and every render fails with an invalid-hook error. The tree
# is readable, deliberately: the solver's own smoke test needs a runner, and a
# task that fails on plumbing the solver could not observe is no test of the
# design. What it does not get is the graded scenarios; see below.
#
# Official images come from AWS's mirror rather than Docker Hub, pinned by
# digest: Hub rate-limits CodeBuild's shared egress address with 429s, and a
# floating tag means two runs of the same task are not the same task.
FROM public.ecr.aws/docker/library/node@sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1001 -s /bin/bash agent

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

# /logs/verifier holds the verdict, the per-rule detail and the deliverable
# snapshot, so the account being graded must not be able to read it -- the agent
# must get `Permission denied`, not merely an absent file.
# Nothing created it before, so the verifier's own `mkdir -p` made it with root's
# umask and left the reward world-readable. Root creating it 700 answers both,
# because the verifier runs as root; `tests/test.sh` re-asserts the mode at run
# time so a directory the platform recreates cannot come back readable. /logs
# itself stays traversable: Harbor puts the agent's own logs beside this.
RUN mkdir -p /logs/verifier \
    && chown root:root /logs /logs/verifier \
    && chmod 755 /logs \
    && chmod 700 /logs/verifier

WORKDIR /deps
COPY deps/package.json /deps/package.json
RUN npm install --no-audit --no-fund --loglevel=error \
    && npm cache clean --force

# The workspace: everything the agent can see and change.
COPY --chown=agent:agent workspace /workspace
RUN ln -s /deps/node_modules /workspace/node_modules

# The graded scenarios are not in this image at all. The fixtures, the seeded
# records, the interleavings and the cases that decide each rule arrive at
# /tests when the verifier runs, after the agent has stopped -- so a solver
# cannot run the graded suite, and cannot fit an answer to a scenario it has
# read. The workspace ships a smoke test instead: enough to tell a broken
# build from a wrong design, and none of the situations that are graded.
#
# The directory is made here, root-owned and unreadable, so that material
# unpacked into it is out of reach even if it arrives while the agent is still
# working.
RUN mkdir -p /tests && chown root:root /tests && chmod 700 /tests

# Node resolves dependencies by walking up from the importer, and the graded
# suite runs from a directory the harness mounts, which may be read-only and
# cannot be given a link of its own. One at the root answers for any of them.
RUN ln -s /deps/node_modules /node_modules

# A pristine copy, so a verifier run can tell what the agent changed and a
# repeated run can put the tree back where it started.
RUN cp -a /workspace /opt/workspace-pristine

# The transform cache cannot live under a read-only dependency tree.
ENV VITE_CACHE_DIR=/tmp/vite-cache \
    MOCKLINEAR_URL=http://127.0.0.1:4570 \
    TZ=Etc/UTC \
    NODE_OPTIONS=--max-old-space-size=3072
RUN mkdir -p /tmp/vite-cache /tmp/vite-cache-grade && chmod 777 /tmp/vite-cache /tmp/vite-cache-grade

WORKDIR /workspace
COPY task-init.sh /usr/local/bin/task-init.sh
RUN chmod 0755 /usr/local/bin/task-init.sh
USER root
ENTRYPOINT ["/usr/local/bin/task-init.sh"]
CMD ["sleep", "infinity"]
