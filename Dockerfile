FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/uar \
    UAR_SESSION_REPOSITORY=sqlite \
    UAR_SESSION_REPOSITORY_PATH=/data/runtime_sessions.db \
    UAR_IDENTITY_DB_PATH=/data/runtime_users.db

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY scripts /app/scripts
COPY README.md /app/README.md
COPY BLUEPRINT_MASTER_v1.md /app/BLUEPRINT_MASTER_v1.md
COPY docs /app/docs
COPY .chainlit /app/.chainlit

RUN useradd --create-home --home-dir /home/uar --shell /usr/sbin/nologin uar \
    && mkdir -p /data \
    && chown -R uar:uar /app /data /home/uar

USER uar

EXPOSE 8000

CMD ["chainlit", "run", "app/ui/chainlit_app.py", "--host", "0.0.0.0", "--port", "8000"]
