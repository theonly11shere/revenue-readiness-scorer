FROM python:3.11-slim

# Install system deps for Playwright
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install Chromium to /app/.playwright (accessible by any user)
ENV PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
RUN playwright install chromium

# Copy app code
COPY . .

# Ensure screenshots dir exists and is writable
RUN mkdir -p /app/screenshots /app/static/screenshots && chmod 777 /app/screenshots /app/static/screenshots

CMD ["python", "start.py"]