# ---------- frontend build ----------
FROM node:22-bookworm-slim AS webui-builder

WORKDIR /webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui/ ./
RUN npm run build

# ---------- frontend tests ----------
# Runs the same lint and vitest the CI job runs, inside the image, so a
# broken frontend cannot reach a release.
FROM node:22-bookworm-slim AS webui-test

WORKDIR /webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci
COPY webui/ ./
RUN npm run lint && npm test

# ---------- backend tests ----------
# The same suite the CI job runs, inside the image, with the coverage floor
# that CI enforces.
FROM python:3.11-slim AS backend-test

ARG DEBIAN_MIRROR=https://deb.debian.org

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN case "$DEBIAN_MIRROR" in https://*) ;; *) echo "DEBIAN_MIRROR must use HTTPS" >&2; exit 1 ;; esac && \
    sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR%/}|g" /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    ffmpeg \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY app ./app
COPY main.py login.py web.py config.yaml ./
COPY tests ./tests

CMD ["python", "-m", "pytest", "tests", "-q", "--cov=app", "--cov=main", "--cov-report=term", "--cov-fail-under=74"]

# ---------- runtime (default) ----------
FROM python:3.11-slim

ARG DEBIAN_MIRROR=https://deb.debian.org

LABEL org.opencontainers.image.title="BiliArchive-Pro" \
      org.opencontainers.image.version="1.9.6" \
      org.opencontainers.image.source="https://github.com/Stars4422335/BiliArchive-Pro" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    BILIARCHIVE_VERSION=1.9.6

WORKDIR /app

RUN case "$DEBIAN_MIRROR" in https://*) ;; *) echo "DEBIAN_MIRROR must use HTTPS" >&2; exit 1 ;; esac && \
    sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR%/}|g" /etc/apt/sources.list.d/debian.sources && \
    apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    ffmpeg \
    tzdata \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy only runtime files. Local credentials and planning files can never enter the image.
COPY app ./app
COPY main.py login.py web.py config.yaml LICENSE README.md ./
COPY --from=webui-builder /webui/dist ./webui/dist
RUN mkdir -p /app/data /app/downloads /app/bin

VOLUME ["/app/data", "/app/downloads", "/app/bin"]

# WebUI 服务端口（compose 中由 biliarchive-web 映射；核心引擎容器不监听端口）
EXPOSE 8000

CMD ["python", "main.py", "--cli"]
