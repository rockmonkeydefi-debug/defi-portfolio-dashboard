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

# Note: env vars are loaded by python-dotenv in the app, not here
# The shell export was removed because it mangles values with $ and special chars

exec "$@"
