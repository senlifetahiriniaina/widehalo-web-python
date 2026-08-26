#!/usr/bin/env bash
set -e

cd /app/widehalo
python manage.py migrate --noinput
exec "$@"
