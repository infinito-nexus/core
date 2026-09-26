ARG DOCS_IMAGE
ARG DOCS_VERSION

FROM ${DOCS_IMAGE}:${DOCS_VERSION}

ARG DOCS_SOURCE_REPO

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update \
  && apt-get -o Acquire::Retries=3 install -y --no-install-recommends git pandoc \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
  myst-parser \
  pathspec \
  pyyaml \
  sphinx \
  sphinxawesome-theme \
  "infinito-nexus[deploy] @ git+${DOCS_SOURCE_REPO}"

COPY ./sphinx/python/ /app/
COPY ./sphinx/javascript/ /app/infinito_docs/assets/js/

ARG MERMAID_VERSION
ARG MERMAID_SHA256
ADD --chmod=0644 --checksum=sha256:${MERMAID_SHA256} \
  https://cdn.jsdelivr.net/npm/mermaid@${MERMAID_VERSION}/dist/mermaid.min.js \
  /app/infinito_docs/assets/js/mermaid.min.js
ADD ./sphinx/snapshot.tar.gz /snapshot/

ENV PYTHONPATH=/app
WORKDIR /app

EXPOSE 8000

CMD ["python", "-m", "infinito_docs.server"]
