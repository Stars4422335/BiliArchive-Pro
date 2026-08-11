FROM python:3.11-slim

ARG DEBIAN_MIRROR=https://deb.debian.org

LABEL org.opencontainers.image.title="BiliArchive-Pro" \
      org.opencontainers.image.version="1.2.0" \
      org.opencontainers.image.source="https://github.com/Stars4422335/BiliArchive-Pro" \
      org.opencontainers.image.licenses="GPL-3.0-only"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    BILIARCHIVE_VERSION=1.2.0

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
COPY main.py login.py config.yaml LICENSE README.md ./
RUN mkdir -p /app/data /app/downloads /app/bin

VOLUME ["/app/data", "/app/downloads", "/app/bin"]

CMD ["python", "main.py", "--cli"]
