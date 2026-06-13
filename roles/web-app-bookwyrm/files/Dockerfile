# BookWyrm v0.8+ uses pyproject.toml/PEP735, so the install needs pip>=25.1 for `--group`.
ARG BOOKWYRM_IMAGE
ARG BOOKWYRM_VERSION
FROM ${BOOKWYRM_IMAGE}:${BOOKWYRM_VERSION} AS builder

# libsass-dev + SYSTEM_SASS=True avoids the in-tree libsass build (~25 min on arm64).
RUN rm -rf /var/lib/apt/lists/* \
  && apt-get update && apt-get install -y --no-install-recommends \
    git build-essential libpq-dev \
    libjpeg-dev zlib1g-dev libxml2-dev libxslt1-dev libffi-dev libmagic-dev \
    libsass-dev gettext tidy \
  && rm -rf /var/lib/apt/lists/*

ENV SYSTEM_SASS=True

WORKDIR /src
ARG BOOKWYRM_REPOSITORY
ARG BOOKWYRM_REF
RUN git clone --depth=1 --branch "${BOOKWYRM_REF}" "${BOOKWYRM_REPOSITORY}" .

# Resolve PEP 735 `[dependency-groups].main` into an isolated venv.
RUN python -m venv /venv \
 && /venv/bin/pip install --upgrade "pip>=25.1.0" \
 && /venv/bin/pip install --group main


FROM ${BOOKWYRM_IMAGE}:${BOOKWYRM_VERSION}
ENV PYTHONUNBUFFERED=1
ENV PATH=/venv/bin:$PATH
ENV SYSTEM_SASS=True
WORKDIR /app

# libsass1 is the runtime sibling of the build-time libsass-dev.
RUN rm -rf /var/lib/apt/lists/* \
  && apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    libjpeg62-turbo zlib1g libxml2 libxslt1.1 libffi8 libmagic1 \
    libsass1 gettext tidy \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
COPY --from=builder /src /app

COPY header_auth.py /app/bookwyrm/header_auth.py
COPY settings_patch.py /tmp/settings_patch.py
RUN cat /tmp/settings_patch.py >> /app/bookwyrm/settings.py

RUN adduser --disabled-password --gecos '' bookwyrm \
 && mkdir -p /app/data /app/media \
 && chown -R bookwyrm:bookwyrm /app /venv

USER bookwyrm
