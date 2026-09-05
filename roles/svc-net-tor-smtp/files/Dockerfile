# Tor SMTP gateway: receives SMTP from the active mail provider and relays each
# .onion recipient through Tor's SOCKS5 listener. aiosmtpd is the SMTP server,
# PySocks the SOCKS client — both pinned so the image is reproducible.
ARG PY_BASE
FROM ${PY_BASE}

RUN pip install --no-cache-dir "aiosmtpd==1.4.6" "PySocks==1.7.1"

COPY tor_smtp_gateway.py /usr/local/bin/tor_smtp_gateway.py

RUN adduser --system --no-create-home --group gateway
USER gateway

ENTRYPOINT ["python", "/usr/local/bin/tor_smtp_gateway.py"]
