FROM python:3.11-slim

WORKDIR /app

# System deps Pillow needs for image handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Koyeb injects PORT; bot.py already reads it via os.environ.get("PORT", 10000)
ENV PORT=8000
EXPOSE 8000

CMD ["python", "bot.py"]
