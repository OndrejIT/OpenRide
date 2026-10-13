#!/bin/sh
set -e
python /app/backend/manage.py migrate --noinput
exec "$@"
