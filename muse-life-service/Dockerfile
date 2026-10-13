FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir /voices && python -m piper.download_voices --download-dir /voices es_MX-ald-medium
COPY app.py .
RUN useradd -u 10001 -m muse && mkdir /cache && chown muse /cache
USER muse
ENV PYTHONUNBUFFERED=1
CMD ["python", "app.py"]
