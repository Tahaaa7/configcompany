#!/bin/sh
set -e
if [ "$USE_ALEMBIC" = "1" ]; then alembic upgrade head; fi
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
