#!/bin/sh
set -eu

HTTP_TEMPLATE="/etc/nginx/nanostore-http.conf.template"
HTTPS_TEMPLATE="/etc/nginx/nanostore-https.conf.template"
TARGET="/etc/nginx/conf.d/default.conf"

if [ "${ENABLE_HTTPS:-1}" = "1" ] \
  && [ -f /etc/nginx/certs/fullchain.pem ] \
  && [ -f /etc/nginx/certs/privkey.pem ]; then
  envsubst '${SERVER_NAME} ${HTTPS_PORT}' < "$HTTPS_TEMPLATE" > "$TARGET"
  echo "nginx: using HTTPS config"
else
  envsubst '${SERVER_NAME}' < "$HTTP_TEMPLATE" > "$TARGET"
  echo "nginx: using HTTP-only config"
fi
