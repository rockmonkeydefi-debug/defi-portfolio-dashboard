#!/bin/sh
# Link persistent config into the app directory.
# The config volume is mounted at /app/config and survives rebuilds.
# On a truly fresh start (empty volume), seed from .env.example once.
CONFIG_DIR=/app/config

mkdir -p "$CONFIG_DIR"

# --- .env -----------------------------------------------------------
if [ ! -f "$CONFIG_DIR/.env" ]; then
  cp /app/.env.example "$CONFIG_DIR/.env"
  echo "[entrypoint] Created initial .env from .env.example — configure via the UI or edit the file directly."
fi
# Force-remove any existing file/symlink then create symlink
rm -f /app/.env
ln -s "$CONFIG_DIR/.env" /app/.env
echo "[entrypoint] .env -> $CONFIG_DIR/.env"

# --- wallet_config.json ---------------------------------------------
if [ ! -f "$CONFIG_DIR/wallet_config.json" ]; then
  if [ -f /app/wallet_config.json.example ]; then
    cp /app/wallet_config.json.example "$CONFIG_DIR/wallet_config.json"
  else
    echo '{}' > "$CONFIG_DIR/wallet_config.json"
  fi
  echo "[entrypoint] Created initial wallet_config.json"
fi
rm -f /app/wallet_config.json
ln -s "$CONFIG_DIR/wallet_config.json" /app/wallet_config.json
echo "[entrypoint] wallet_config.json -> $CONFIG_DIR/wallet_config.json"

# --- Export env vars so gunicorn inherits them -----------------------
if [ -f /app/.env ]; then
  while IFS='=' read -r key value; do
    case "$key" in
      \#*|'') continue ;;
    esac
    value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")
    export "$key=$value"
  done < /app/.env
fi

exec "$@"
