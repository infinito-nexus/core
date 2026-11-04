ARG PY_BASE
FROM ${PY_BASE}

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY tor_smtp_gateway.py /usr/local/bin/tor_smtp_gateway.py

RUN adduser --system --no-create-home --group gateway
USER gateway

ENTRYPOINT ["python", "/usr/local/bin/tor_smtp_gateway.py"]
