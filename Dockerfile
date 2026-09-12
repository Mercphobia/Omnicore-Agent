# Stage 1 — Build dependencies
FROM python:3.11-slim AS builder

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir \
        httpx \
        pyyaml \
        rich \
        duckduckgo-search

# Stage 2 — Production
FROM python:3.11-slim

LABEL org.opencontainers.image.title="OmniCore v3" \
      org.opencontainers.image.description="OmniCore v3 — autonomous agent platform" \
      org.opencontainers.image.version="3.0.0" \
      org.opencontainers.image.source="https://github.com/omnicore/omnicore" \
      org.opencontainers.image.licenses="MIT"

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create non-root user
RUN useradd --create-home --shell /bin/bash omnicore

WORKDIR /home/omnicore/app
COPY . .

RUN chown -R omnicore:omnicore /home/omnicore

USER omnicore
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

ENTRYPOINT ["python", "omnicore.py", "--server"]