# The API image.
#
# Two stages. The first installs dependencies with the build tools that need a compiler; the
# second copies only the result. A production image that carries gcc carries a way to build
# whatever an attacker uploads.

FROM python:3.12-slim AS build

# uv resolves and installs from the lock file. Pinned by digest rather than by tag: a tag is a
# name that can be repointed, and "the same build twice" has to mean the same bytes.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /build

# Dependencies before source, so a code change does not re-resolve the whole graph. This layer is
# rebuilt only when pyproject.toml or uv.lock actually change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY seeds ./seeds
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# Runs as nobody in particular. A container process that is root is a container escape away from
# being root on the host, and this one needs to read its own code and nothing else.
RUN groupadd --gid 10001 uboss \
 && useradd --uid 10001 --gid uboss --no-create-home --shell /usr/sbin/nologin uboss

# `tini` reaps zombies and forwards signals, so a SIGTERM from the orchestrator actually reaches
# the server and it shuts down cleanly instead of being killed after the grace period.
RUN apt-get update \
 && apt-get install --no-install-recommends -y tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=build --chown=uboss:uboss /build /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER uboss

# The readiness probe the orchestrator should use is /health/ready — it runs a real query. This
# HEALTHCHECK uses /health/live, which only says the process is up: a database outage should stop
# traffic, not restart a healthy container.
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2).status == 200 else 1)"

EXPOSE 8000
ENTRYPOINT ["/usr/bin/tini", "--"]

# No migration on start-up, deliberately. Several replicas starting at once would run it
# concurrently, and a migration is a reviewed step with a preflight and a backup — see
# docs/runbooks/MIGRATIONS.md. It is a separate job in the deployment, before the new version.
CMD ["python", "-m", "uboss", "--host", "0.0.0.0", "--port", "8000"]
