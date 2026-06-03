FROM python:3.12-slim

WORKDIR /app

# PINGVerter pulls numpy, pandas, pyproj, pillow — allow time for pip resolve.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SONAR_HOST=0.0.0.0
ENV SONAR_DATA_DIR=/data
# Railway injects PORT at runtime; local default is 8080 in resolve_port().
ENV PORT=8080

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8080\")}/api/health')" || exit 1

CMD ["sh", "-c", "python sonar_cli.py serve --host 0.0.0.0 --port ${PORT:-8080} --data-dir ${SONAR_DATA_DIR:-/data}"]
