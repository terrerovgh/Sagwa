FROM python:3.13-slim@sha256:bf44cdfcb76cd3b41e879bc058fc37ec5872002ccfde7fcb765e218cde0cd79c
WORKDIR /app
COPY server.py /app/server.py
USER 65534:65534
ENV HEALTHY=1
CMD ["python", "server.py"]
