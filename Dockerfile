FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m botuser
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/data && chown -R botuser:botuser /app
# root se start -> volume permission theek -> setpriv se botuser ban jata hai
CMD ["/app/entrypoint.sh"]
