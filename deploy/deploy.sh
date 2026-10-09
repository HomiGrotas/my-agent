#!/usr/bin/env bash
# Deploys the agent to the server over SSH: builds the Docker image locally (with the local article
# corpus) and loads it on the server, then installs/enables the systemd units (weekly send + the
# always-running Telegram bot, restarted to use the new image). The server has ~1 GB of RAM, so building there is slow and may run out of memory.
#
# Server state lives in $APP_DIR and is kept across deploys: .env, .logfire/, data/ (Telegram
# subscribers), .wwebjs_auth/ (linked WhatsApp session). The files to deploy (the systemd units, or the
# whole build context with --build-on-server) are uploaded to $APP_DIR/build, recreated on every deploy.
#
# Usage: deploy/deploy.sh [--build-on-server] [--env] [--whatsapp-session]
#   --build-on-server   upload the code and build the image on the server instead of locally
#   --env               upload the local .env (without DEV_MODE); the server's is kept as .env.bak
#   --whatsapp-session  upload the local linked WhatsApp session (whatsapp/.wwebjs_auth), replacing the server's
# Env: DEPLOY_HOST (default oracle-medics-ubuntu), DEPLOY_APP_DIR (default /home/ubuntu/my-agent)
set -euo pipefail

HOST="${DEPLOY_HOST:-oracle-medics-ubuntu}"
APP_DIR="${DEPLOY_APP_DIR:-/home/ubuntu/my-agent}"
UPLOAD_ENV=false
UPLOAD_WHATSAPP_SESSION=false
BUILD_ON_SERVER=false
for arg in "$@"; do
    case "$arg" in
        --env) UPLOAD_ENV=true ;;
        --whatsapp-session) UPLOAD_WHATSAPP_SESSION=true ;;
        --build-on-server) BUILD_ON_SERVER=true ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain)" ]; then
    echo "Warning: deploying uncommitted changes" >&2
fi
if [ ! -d res/parashot_articles ] || [ ! -f whatsapp/package-lock.json ]; then
    echo "Missing res/parashot_articles or whatsapp/package-lock.json - run the fetch scripts / npm install first" >&2
    exit 1
fi

if $BUILD_ON_SERVER; then
    FILES=(Dockerfile .dockerignore pyproject.toml uv.lock README.md main.py my_agent res deploy
        whatsapp/send.js whatsapp/package.json whatsapp/package-lock.json)
else
    FILES=(deploy)
fi
echo "==> Uploading ${FILES[*]} ($(git rev-parse --short HEAD)) to $HOST:$APP_DIR/build"
tar -czf - --exclude=__pycache__ "${FILES[@]}" \
    | ssh "$HOST" "rm -rf '$APP_DIR/build' && mkdir -p '$APP_DIR/build' && tar -xzf - -C '$APP_DIR/build'"

if $UPLOAD_ENV; then
    echo "==> Uploading .env (DEV_MODE removed; previous kept as .env.bak)"
    grep -v '^DEV_MODE=' .env | ssh "$HOST" "cd '$APP_DIR' && { [ ! -f .env ] || cp -p .env .env.bak; } \
        && umask 077 && cat > .env.new && mv .env.new .env"
fi

if $UPLOAD_WHATSAPP_SESSION; then
    echo "==> Uploading the linked WhatsApp session"
    # Browser caches and profile locks aren't needed to restore the session
    tar -czf - -C whatsapp \
        --exclude='Cache' --exclude='Code Cache' --exclude='GPUCache' --exclude='Singleton*' .wwebjs_auth \
        | ssh "$HOST" "cd '$APP_DIR' && rm -rf .wwebjs_auth.new && mkdir .wwebjs_auth.new \
            && tar -xzf - -C .wwebjs_auth.new --strip-components=1 \
            && rm -rf .wwebjs_auth && mv .wwebjs_auth.new .wwebjs_auth"
fi

# Seed the server's Telegram subscribers from the local file, but never overwrite the server's
if [ -f data/telegram_subscribers.json ]; then
    ssh "$HOST" "mkdir -p '$APP_DIR/data' && [ ! -f '$APP_DIR/data/telegram_subscribers.json' ] \
        && cat > '$APP_DIR/data/telegram_subscribers.json' && echo '==> Seeded Telegram subscribers' \
        || true" < data/telegram_subscribers.json
fi

if $BUILD_ON_SERVER; then
    echo "==> Building the Docker image on the server"
    ssh "$HOST" "cd '$APP_DIR/build' && docker build -q -t my-agent:latest ."
else
    echo "==> Building the Docker image locally"
    docker build --platform linux/amd64 -t my-agent:latest .
    echo "==> Uploading the image to the server"
    docker save my-agent:latest | gzip | ssh "$HOST" "gunzip | docker load"
fi

echo "==> Installing systemd units"
ssh "$HOST" "set -e
    for unit in '$APP_DIR'/build/deploy/*.service '$APP_DIR'/build/deploy/*.timer; do
        sed 's|__APP_DIR__|$APP_DIR|g' \"\$unit\" | sudo tee /etc/systemd/system/\$(basename \"\$unit\") > /dev/null
    done
    # Replaced by the always-running my-agent-telegram-bot.service
    if [ -f /etc/systemd/system/my-agent-subscribers.timer ]; then
        sudo systemctl disable --now my-agent-subscribers.timer
        sudo rm -f /etc/systemd/system/my-agent-subscribers.timer /etc/systemd/system/my-agent-subscribers.service
    fi
    sudo systemctl daemon-reload
    sudo systemctl enable --now my-agent.timer my-agent-telegram-bot.service
    sudo systemctl restart my-agent-telegram-bot.service
    systemctl list-timers --no-pager 'my-agent*'
    systemctl status --no-pager --lines=0 my-agent-telegram-bot.service"

echo "==> Deployed"
