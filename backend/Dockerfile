FROM node:22-bookworm-slim AS node
FROM debian:bookworm-slim AS whisper
# git is needed at configure time: ggml's CMakeLists calls find_program(GIT_EXE) and
# fails the build outright when it is missing, even though the source arrives by tarball.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake curl ca-certificates git && rm -rf /var/lib/apt/lists/*
WORKDIR /build
# Immutable whisper.cpp v1.7.6 commit and immutable base.en model repository revision.
RUN curl -fsSL https://github.com/ggml-org/whisper.cpp/archive/a8d002cfd879315632a579e73f0148d06959de36.tar.gz | tar xz --strip-components=1 \
 && cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DWHISPER_CURL=OFF \
 && cmake --build build --config Release -j2 --target whisper-cli \
 && mkdir -p /models \
 && curl -fL --retry 3 https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.en.bin -o /models/ggml-base.en.bin

FROM python:3.13-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    HYPECHECK_PLAYWRIGHT_DIR=/opt/video/node_modules/playwright \
    WHISPER_MODEL=/opt/whisper/ggml-base.en.bin
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY backend/app/video/package*.json /opt/video/
RUN cd /opt/video && npm ci --no-audit --no-fund \
 && node node_modules/playwright/cli.js install --with-deps chromium \
 && chmod -R a+rX /opt/playwright-browsers
COPY --from=whisper /build/build/bin/whisper-cli /usr/local/bin/whisper-cli
COPY --from=whisper /models/ggml-base.en.bin /opt/whisper/ggml-base.en.bin
WORKDIR /app
COPY backend/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r requirements.lock
COPY backend /app
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home hypecheck && mkdir -p /data && chown hypecheck /data
USER hypecheck
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
