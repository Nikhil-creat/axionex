# syntax=docker/dockerfile:1.7
# ---------- builder: resolve wheels into an isolated venv ----------
FROM python:3.11-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /build
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# ---------- runtime: slim, non-root ----------
FROM python:3.11-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/app HF_HOME=/home/app/.cache/huggingface TORCH_HOME=/home/app/.cache/torch
COPY --from=builder /opt/venv /opt/venv
RUN useradd -m -u 10001 app && mkdir -p /home/app/.cache && chown -R app:app /home/app
WORKDIR /srv
COPY . .
RUN chmod +x scripts/entrypoint.sh && chown -R app:app /srv
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=60s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"
ENTRYPOINT ["./scripts/entrypoint.sh"]
CMD ["api"]
