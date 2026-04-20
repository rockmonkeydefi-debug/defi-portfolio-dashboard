FROM python:3.11-slim

WORKDIR /app

# Install system deps for cryptography/bcrypt/hdwallet C extensions
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev libc-dev && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy app code
COPY . .

# Ensure seed templates are present (even if .dockerignore strips the real configs)
# .env.example and wallet_config.json.example are NOT in .dockerignore
# so they'll be available for first-run seeding.

# Create directories
RUN mkdir -p /app/data /app/config

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 5001

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "4", "--timeout", "360", "web_portfolio:app"]
