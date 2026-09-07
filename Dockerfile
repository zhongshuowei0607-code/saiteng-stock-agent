FROM --platform=linux/amd64 python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Shanghai \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    MALLOC_ARENA_MAX=2 STOCK_AGENT_CONFIG_DIR=/app/config
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt && \
    rm -rf /root/.cache/pip
COPY app ./app
COPY config ./defaults/config
COPY run.py .
COPY VERSION .
RUN mkdir -p config data reports logs backup && \
    cp -n defaults/config/* config/ && \
    useradd --uid 1000 --create-home agent && chown -R agent:agent /app
USER agent
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=40s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5)"
CMD ["python", "run.py", "server"]
