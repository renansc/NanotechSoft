#!/bin/sh
set -eu

HTTP_TEMPLATE="/etc/nginx/riobranco-http.conf.template"
HTTPS_TEMPLATE="/etc/nginx/riobranco-https.conf.template"
TARGET="/etc/nginx/conf.d/default.conf"

if [ "${RB_ENABLE_HTTPS:-0}" = "1" ] \
  && [ -f /etc/nginx/certs/fullchain.pem ] \
  && [ -f /etc/nginx/certs/privkey.pem ]; then
  envsubst '${RB_SERVER_NAME} ${RB_HTTPS_PORT}' < "$HTTPS_TEMPLATE" > "$TARGET"
  echo "nginx: using HTTPS config"
else
  envsubst '${RB_SERVER_NAME}' < "$HTTP_TEMPLATE" > "$TARGET"
  echo "nginx: using HTTP-only config"
fi
