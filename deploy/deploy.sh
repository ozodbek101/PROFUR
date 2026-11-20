#!/usr/bin/env bash
# Runs on the server after CI has synced the code into /var/www/wms/app.
# Installs dependencies, migrates, collects static files, restarts gunicorn and checks
# that the site answers. Exits non-zero (failing the CI job) if anything goes wrong.
set -euo pipefail

APP_ROOT=/var/www/wms
APP_DIR=$APP_ROOT/app
VENV=$APP_ROOT/venv
APP_PORT=8001

cd "$APP_DIR"
set -a; . "$APP_ROOT/.env"; set +a

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --disable-pip-version-check -r requirements.txt

"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput --verbosity 0
"$VENV/bin/python" manage.py check

sudo systemctl restart wms

for _ in $(seq 1 30); do
  # Present the request as nginx does (HTTPS terminated in front), so the SSL
  # redirect does not turn the check into a 301.
  code=$(curl -s -o /dev/null -w '%{http_code}' -H 'X-Forwarded-Proto: https' \
    "http://127.0.0.1:$APP_PORT/accounts/login/" || true)
  if [ "$code" = 200 ]; then
    echo "Deployed: login page answers 200."
    exit 0
  fi
  sleep 1
done

echo "Health check failed (last status: ${code:-none})" >&2
sudo journalctl -u wms -n 60 --no-pager >&2
exit 1
