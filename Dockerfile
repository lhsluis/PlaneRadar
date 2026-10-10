FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd --gid 65536 dockergroup \
    && useradd --create-home --uid 1030 --gid 65536 dockerlimited \
    && mkdir -p /data \
    && chown -R dockerlimited:dockergroup /app /data
USER dockerlimited

ENV PYTHONUNBUFFERED=1 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5000 \
    PLANE_RADAR_LAT=-21.805684 \
    PLANE_RADAR_LON=-48.139653 \
    PLANE_RADAR_DISTANCE=25 \
    PLANE_RADAR_POLLING=10 \
    PLANE_RADAR_AIRLINE_LOGO_API_KEY= \
    PLANE_RADAR_CACHE_DB=/data/planeradar-cache.sqlite3

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "app:app"]
