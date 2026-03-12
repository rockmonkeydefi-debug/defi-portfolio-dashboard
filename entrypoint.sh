#!/bin/sh
# Ensure config files exist in the persistent volume
CONFIG_DIR=/app/config

mkdir -p "$CONFIG_DIR"

# Create .env if missing
if [ ! -f "$CONFIG_DIR/.env" ]; then
  if [ -f /app/.env.example ]; then
    cp /app/.env.example "$CONFIG_DIR/.env"
    echo "Created .env from example"
  else
    touch "$CONFIG_DIR/.env"
  fi
fi

# Create wallet_config.json if missing
if [ ! -f "$CONFIG_DIR/wallet_config.json" ]; then
  echo '{}' > "$CONFIG_DIR/wallet_config.json"
  echo "Created empty wallet_config.json"
fi

# Symlink config files to app directory
ln -sf "$CONFIG_DIR/.env" /app/.env
ln -sf "$CONFIG_DIR/wallet_config.json" /app/wallet_config.json

# Load env vars from .env
export $(grep -v '^#' "$CONFIG_DIR/.env" | xargs -r)

exec "$@"
