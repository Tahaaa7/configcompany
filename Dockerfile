FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*   # pg_dump برای بکاپ (نسخه کلاینت ≥ نسخه سرور)
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY web web
COPY alembic alembic
COPY alembic.ini start.sh ./
CMD ["./start.sh"]
