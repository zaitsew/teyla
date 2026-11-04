FROM python:3.12.7-alpine3.20
WORKDIR /app
COPY server.py /app/server.py
# uid 1000 owns the data volume on the host, so the pull over SSH (same uid) can read and delete what the service wrote.
USER 1000:1000
ENV RC_DATA=/data RC_KEYS=/keys/keys.txt RC_PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"]
CMD ["python", "/app/server.py"]
