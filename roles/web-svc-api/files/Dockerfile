ARG API_IMAGE
ARG API_VERSION

FROM ${API_IMAGE}:${API_VERSION}

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update \
  && apt-get -o Acquire::Retries=3 install -y --no-install-recommends git \
  && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
  babel \
  fastapi \
  pyyaml \
  uvicorn

COPY ./api/python/ /app/
ADD ./api/snapshot.tar.gz /snapshot/

ENV PYTHONPATH=/app
WORKDIR /app

CMD ["python", "-m", "infinito_api"]
