# syntax=docker/dockerfile:1
# AI Personal CFO — frontend (Vite/React SPA) container.
#
# Multi-stage build: compile the SPA with Vite in Node, then serve the static
# bundle with nginx. nginx also proxies /api to the backend so the SPA can talk
# to the API without CORS configuration.
#
# Build:
#   docker build -t ai-cfo-frontend -f frontend/Dockerfile \
#       --build-arg VITE_API_BASE=http://backend:8000 .
#
# At runtime set BACKEND_URL to the backend's reachable URL. In Coolify, link
# the frontend service to the backend service and Coolify injects the backend's
# internal URL automatically — see the Coolify config notes in the repo root.

FROM node:20-alpine AS build

WORKDIR /app

# Install deps first for layer caching.
COPY package*.json ./
RUN npm ci

# Copy source and build-time env.
COPY . .
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}

RUN npm run build

# ---------------------------------------------------------------------------
# Runtime: nginx serving the static bundle + /api proxy.
# ---------------------------------------------------------------------------
FROM nginx:alpine

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY nginx.conf.template /etc/nginx/templates/website.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

ENV BACKEND_URL=""

EXPOSE 80

ENTRYPOINT ["/entrypoint.sh"]