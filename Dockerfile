FROM python:3.11-slim

WORKDIR /app

# Install system deps + fonts-unifont (replaces deprecated ttf-unifont)
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates \
    fonts-unifont \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    libgtk-3-0 libx11-xcb1 libxcb-dri3-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright chromium WITHOUT --with-deps (deps already installed above)
RUN playwright install chromium

COPY app/ .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
