#!/bin/sh
# Persistent config lives on the Railway volume at /app/data.
# The app reads DOTENV_PATH to find .env — no symlinks needed.
CONFIG_DIR=/app/data

mkdir -p "$CONFIG_DIR"

# --- .env -----------------------------------------------------------
# Only create from example if no .env exists on the volume yet.
if [ ! -f "$CONFIG_DIR/.env" ]; then
  cp /app/.env.example "$CONFIG_DIR/.env"
  echo "[entrypoint] Created initial .env from .env.example — configure via the UI or edit the file directly."
fi
export DOTENV_PATH="$CONFIG_DIR/.env"
echo "[entrypoint] DOTENV_PATH=$DOTENV_PATH"

# --- wallet_config.json ---------------------------------------------
# Only create if no wallet_config.json exists on the volume yet.
if [ ! -f "$CONFIG_DIR/wallet_config.json" ]; then
  if [ -f /app/wallet_config.json.example ]; then
    cp /app/wallet_config.json.example "$CONFIG_DIR/wallet_config.json"
  else
    echo '{}' > "$CONFIG_DIR/wallet_config.json"
  fi
  echo "[entrypoint] Created initial wallet_config.json"
fi
export WALLET_CONFIG_PATH="$CONFIG_DIR/wallet_config.json"
echo "[entrypoint] WALLET_CONFIG_PATH=$WALLET_CONFIG_PATH"

# --- Export env vars so gunicorn inherits them -----------------------
while IFS='=' read -r key value; do
  case "$key" in
    \#*|'') continue ;;
  esac
  # Skip if already set in the environment (e.g. Railway variables take precedence)
  eval "[ -n \"\${${key}+x}\" ]" && continue
  value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")
  export "$key=$value"
done < "$CONFIG_DIR/.env"

exec "$@"
