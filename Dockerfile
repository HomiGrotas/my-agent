FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Node.js + Chromium for the whatsapp-web.js sender (Puppeteer uses the system Chromium)
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm chromium \
    && rm -rf /var/lib/apt/lists/*
ENV PUPPETEER_SKIP_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    WHATSAPP_SESSION_DIR=/app/whatsapp/.wwebjs_auth

WORKDIR /app

# WhatsApp sender dependencies
COPY whatsapp/package.json whatsapp/package-lock.json ./whatsapp/
RUN npm ci --omit=dev --prefix whatsapp

# Install dependencies first so they're cached across code changes
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Project code + local article corpus. The project is installed editable (uv's default),
# so ARTICLES_DIR in get_parasha_articles.py resolves to /app/res/parashot_articles.
COPY main.py ./
COPY whatsapp/send.js ./whatsapp/
COPY my_agent ./my_agent
COPY res ./res
RUN uv sync --frozen --no-dev

CMD ["/app/.venv/bin/python", "main.py"]
