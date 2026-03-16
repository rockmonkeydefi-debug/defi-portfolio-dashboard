#!/bin/sh
# Ensure config files exist in the persistent volume
CONFIG_DIR=/app/config

mkdir -p "$CONFIG_DIR"

# Create .env if missing — prefer the baked-in .env over .env.example
if [ ! -f "$CONFIG_DIR/.env" ]; then
  if [ -f /app/.env ] && [ ! -L /app/.env ]; then
    cp /app/.env "$CONFIG_DIR/.env"
    echo "Created .env from baked-in config"
  elif [ -f /app/.env.example ]; then
    cp /app/.env.example "$CONFIG_DIR/.env"
    echo "Created .env from example"
  else
    touch "$CONFIG_DIR/.env"
  fi
fi

# Create wallet_config.json if missing — prefer baked-in over empty
if [ ! -f "$CONFIG_DIR/wallet_config.json" ]; then
  if [ -f /app/wallet_config.json ] && [ ! -L /app/wallet_config.json ]; then
    cp /app/wallet_config.json "$CONFIG_DIR/wallet_config.json"
    echo "Created wallet_config.json from baked-in config"
  else
    echo '{}' > "$CONFIG_DIR/wallet_config.json"
    echo "Created empty wallet_config.json"
  fi
fi

# Symlink config files to app directory
ln -sf "$CONFIG_DIR/.env" /app/.env
ln -sf "$CONFIG_DIR/wallet_config.json" /app/wallet_config.json

# Load env vars safely (line by line to handle special chars)
while IFS='=' read -r key value; do
  case "$key" in
    \#*|'') continue ;;  # skip comments and empty lines
  esac
  # Strip surrounding quotes if present
  value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//")
  export "$key=$value"
done < "$CONFIG_DIR/.env"

exec "$@"
