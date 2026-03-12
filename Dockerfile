FROM python:3.11-slim

WORKDIR /app

# Install system deps for cryptography/bcrypt
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy app code
COPY . .

# Create data directory
RUN mkdir -p /app/data

EXPOSE 5001

# Run with gunicorn (production WSGI server)
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "1", "--threads", "4", "--timeout", "120", "web_portfolio:app"]
