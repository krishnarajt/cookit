FROM python:3.11-slim

WORKDIR /app

# gcc and libpq-dev are for psycopg2. Nothing else here needs a system package:
# the PDF exporter is reportlab, which ships its own rendering.
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application.
# --proxy-headers/--forwarded-allow-ips let uvicorn trust the ingress's
# X-Forwarded-Proto. Without them it sees plain http and builds its
# trailing-slash redirects as http:// URLs, which a browser on the https site
# blocks as mixed content.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
