# Runtime image for Bridgy Fed (Flask) with a build step that clones upstream
ARG PY_BASE="python:3.12-bookworm"
FROM ${PY_BASE} AS build

ARG BRIDGY_REPO_URL
ARG BRIDGY_REF

# System deps: git, build tools, curl for healthchecks, and gunicorn
RUN rm -rf /var/lib/apt/lists/* && \
    apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    git build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth=1 --branch "${BRIDGY_REF}" "${BRIDGY_REPO_URL}" ./

# Python deps
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Create oauth_dropins static symlink (upstream expects this)
RUN python - <<'PY'
import oauth_dropins, pathlib, os
target = pathlib.Path(oauth_dropins.__file__).parent / 'static'
link = pathlib.Path('/app/oauth_dropins_static')
try:
    if link.exists() or link.is_symlink():
        link.unlink()
    os.symlink(str(target), str(link))
except FileExistsError:
    pass
print('Symlinked oauth_dropins_static ->', target)
PY

# Final stage. Carry over the application directory AND the python
# site-packages from the build stage so gunicorn / bridgy-fed deps
# are present at runtime; otherwise the entrypoint exits with
# `gunicorn: not found` and the container restarts forever.
FROM ${PY_BASE}

ARG CONTAINER_PORT
ENV PORT=${CONTAINER_PORT}

WORKDIR /app
COPY --from=build /app /app
# Carry the entire /usr/local layer over (Python's site-packages and bin
# scripts), so the python-version-specific path (python3.14, python3.12, …)
# does not have to be hardcoded.
COPY --from=build /usr/local /usr/local

# Non-root good practice
RUN useradd -r -m -d /nonroot appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE ${PORT}
# Upstream flask app entry: 'flask_app:app'
CMD ["sh", "-lc", "exec gunicorn -w 2 -k gthread -b 0.0.0.0:${PORT} flask_app:app"]
