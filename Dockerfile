FROM python:3.12-slim
WORKDIR /app
COPY requirements-pilot.txt .
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r requirements-pilot.txt && pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY . .
RUN mkdir -p /data/uploads /data/artifacts /data/backups
EXPOSE 8000
CMD ["uvicorn","api:app","--host","0.0.0.0","--port","8000","--proxy-headers","--forwarded-allow-ips=*"]
