ARG PIPER_BASE_IMAGE
ARG PIPER_BASE_VERSION
FROM ${PIPER_BASE_IMAGE}:${PIPER_BASE_VERSION}

COPY package-frontend-ca.crt /opt/package-frontend-ca.crt
COPY package-frontend-ca.sh /usr/local/bin/package-frontend-ca.sh
RUN /usr/local/bin/package-frontend-ca.sh

COPY requirements.txt /opt/piper/requirements.txt
RUN python3 -m venv --without-pip /opt/piper \
  && pip --python /opt/piper/bin/python install --no-cache-dir --root-user-action=ignore --require-hashes --only-binary=:all: --requirement /opt/piper/requirements.txt

RUN useradd --system --no-create-home --shell /usr/sbin/nologin piper

COPY server.py /app/server.py

USER piper
ENTRYPOINT ["python3", "/app/server.py", "--piper", "/opt/piper/bin/piper"]
