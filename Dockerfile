FROM python:3.14-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    GIT_SUPPORT_ENV_PATH=/app/data/.env TMPDIR=/app/data/tmp \
    OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import hashlib, pathlib, urllib.request; u='https://huggingface.co/BAAI/bge-m3/resolve/5617a9f61b028005a4858fdac845db406aefb181/tokenizer.json'; b=urllib.request.urlopen(u, timeout=120).read(); assert hashlib.sha256(b).hexdigest() == '21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08'; pathlib.Path('/opt/bge-m3-tokenizer.json').write_bytes(b)"
COPY app.py alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY static ./static
COPY container_start.py ./
EXPOSE 8025
CMD ["python", "container_start.py"]
