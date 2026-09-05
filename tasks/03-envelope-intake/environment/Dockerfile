FROM public.ecr.aws/docker/library/node@sha256:8a34c4ab3ea2c5cd194f07e317b2a8f09461d3c8b05c4e34c8ccd56d56024c4d

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl git jq make procps python3 ripgrep sqlite3 sudo \
        tzdata patch tmux xxd && \
    rm -rf /var/lib/apt/lists/*

# Lets anything in the image run the project's TypeScript without a build step,
# which is how the service is run locally and how the verifier starts it.
RUN npm install -g --no-audit --no-fund tsx@4.19.2

ENV TZ=Etc/UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN useradd --create-home --shell /bin/bash agent

# Terminal hardening. Agents deliver large files as a single pasted heredoc, and
# a pty wedged partway through that paste costs the whole trial.
COPY --chown=root:root hardening/shell-hardening.sh /etc/profile.d/10-shell-hardening.sh
COPY --chown=root:root hardening/tmux.conf /etc/tmux.conf
RUN chmod 0644 /etc/profile.d/10-shell-hardening.sh /etc/tmux.conf && \
    printf '\n. /etc/profile.d/10-shell-hardening.sh\n' >> /etc/bash.bashrc

# Verifier-only material: the graded run and the independent model of the
# specification. The agent account sees an opaque parent directory and nothing
# inside it, in any layer. The generator that produced the run never enters the
# image at all.
RUN install -d -m 0700 -o root -g root /var/lib/task-data /var/lib/task-data/verifier
COPY --chown=root:root --chmod=600 verifier-data/ /var/lib/task-data/verifier/
# `--chmod=600` above applies to directories too, which leaves them without an
# owner execute bit. Root traverses them regardless, so nothing breaks, but a
# directory that cannot be listed by its own owner is an accident waiting to be
# debugged. Files stay 0600, directories become 0700, and nothing is readable to
# anyone but root either way.
RUN chmod -R go-rwx /var/lib/task-data && \
    find /var/lib/task-data -type d -exec chmod u+rwx {} +

RUN install -d -o agent -g agent /app
WORKDIR /app
COPY --chown=agent:agent workspace/ /app/

# The default store lives here and the service writes it, so the agent owns it.
RUN install -d -m 0755 -o agent -g agent /data

# The transport's spool: the default `DESK_SPOOL`, which the service writes to
# when nothing has overridden it. Owned by the agent so the sandbox works out of
# the box; the verifier points DESK_SPOOL somewhere of its own regardless.
RUN install -d -m 0755 -o agent -g agent /var/spool/desk-egress

# sqlite3 ships a prebuilt binding for this platform; the image is built with a
# network and runs without one, so it has to be resolved now.
USER agent
RUN npm install --no-audit --no-fund && \
    node -e "require('sqlite3'); console.log('sqlite3 binding ok')"
USER root

# A root-owned copy of the resolved dependency tree, so a workspace that arrives
# without one can still be exercised.
#
# `npm install` runs at build time because the box has a network then and not
# afterwards, and `node_modules` is in none of the copies we keep: the
# deliverable snapshot excludes it, `pristine_app` excludes it, and a replay
# stages the submitted tree into a fresh sandbox. Without the copy below, a
# staged tree dies at `npm run migrate` with "Cannot find module 'sqlite3'" --
# a trial that graded fine the first time cannot be graded again.
#
# The agent's own /app/node_modules stays real and writable, so a solver who
# runs `npm install` is not handed an EACCES; this is 43MB of insurance beside
# it. The directory has to be called `node_modules`, because node resolves the
# symlink and then walks the *real* parents looking for a dependency of a
# dependency -- under any other name sqlite3 cannot find `bindings`.
RUN install -d -m 0755 -o root -g root /opt/intake-deps && \
    cp -a /app/node_modules /opt/intake-deps/node_modules && \
    chown -R root:root /opt/intake-deps && \
    node -e "require('/opt/intake-deps/node_modules/sqlite3'); console.log('spare sqlite3 binding ok')"

# Root-only copy of the starting sources, so a finished run can be diffed
# against what the box began with. Nothing reads it during scoring.
RUN install -d -m 0700 -o root -g root /var/lib/task-data/pristine_app && \
    tar -C /app --exclude=./node_modules -cf - . \
      | tar -C /var/lib/task-data/pristine_app -xf - && \
    chown -R root:root /var/lib/task-data/pristine_app && \
    chmod -R go-rwx /var/lib/task-data/pristine_app

COPY --chown=root:root task-init.sh /usr/local/bin/task-init.sh
RUN chmod 0755 /usr/local/bin/task-init.sh

# The Gmail workspace the box serves for context. Readable, not writable: it
# stands in for Gmail, it is not part of the deliverable.
COPY --chown=root:root mockgmail/ /opt/mockgmail/mockgmail/
RUN chmod -R a+rX /opt/mockgmail && \
    find /opt/mockgmail -name '__pycache__' -prune -exec rm -rf {} + && \
    install -m 0755 -o root -g root /opt/mockgmail/mockgmail/bin/mockgmail /usr/local/bin/mockgmail && \
    ln -s /usr/local/bin/mockgmail /usr/local/bin/gmail
RUN install -d -m 0755 -o root -g root /opt/gmail-sandbox
COPY --chown=root:root --chmod=0444 sandbox/gmail/ /opt/gmail-sandbox/
RUN PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/mockgmail python3 -m mockgmail.check /opt/gmail-sandbox/public.json
ENV MOCKGMAIL_URL=http://127.0.0.1:4570

# INTAKE_DB and PORT are the service's own configuration; sandbox/notes.md and
# the README document the same names. The verifier overrides both, so nothing is
# graded against the store the box was handed.
ENV INTAKE_DB=/data/intake.db \
    PORT=8080 \
    NODE_OPTIONS=--max-old-space-size=1024 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/usr/local/bin/task-init.sh"]
CMD ["--wait"]
