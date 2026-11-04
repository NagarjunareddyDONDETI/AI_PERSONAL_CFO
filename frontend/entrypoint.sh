#!/usr/bin/env sh
# Runs inside the frontend container at startup.
#
# Replaces ${BACKEND_URL} in the nginx config template with the value of the
# BACKEND_URL environment variable, then starts nginx.
#
# BACKEND_URL should be the backend's reachable URL, e.g.
#   http://ai-personal-cfo-backend:8000
# In Coolify, link the frontend service to the backend service and set this to
# the backend's internal URL (or use the service name above).

set -e

# Remove the stock default configuration so our site config handles everything.
rm -f /etc/nginx/conf.d/default.conf

if [ -z "${BACKEND_URL}" ]; then
    echo "WARNING: BACKEND_URL is not set; /api proxy will be broken."
    BACKEND_URL="http://127.0.0.1:8000"
fi

# envsubst with an explicit list so only ${BACKEND_URL} is substituted; every
# other $variable stays intact for nginx to interpret.
envsubst '${BACKEND_URL}' < /etc/nginx/templates/website.conf.template \
    > /etc/nginx/conf.d/website.conf

exec nginx -g 'daemon off;'