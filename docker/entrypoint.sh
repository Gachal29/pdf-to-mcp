#!/bin/sh
set -eu

# db は compose の healthcheck 通過後に起動するので、ここでは待機しない
python manage.py migrate --noinput

exec "$@"
