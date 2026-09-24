# Build estático del storefront servido por Caddy.
#
# El contexto de build es la raíz del repositorio, no este directorio, porque el servicio en
# Railway se selecciona con RAILWAY_DOCKERFILE_PATH=storefront/Dockerfile en vez de un root
# directory. Por eso cada COPY lleva el prefijo storefront/. En local:
#   docker build -f storefront/Dockerfile .
#
# `VITE_MERCHANT_API_URL` se inlinea en tiempo de build, igual que en la UI del agente.
FROM node:24-slim AS build

WORKDIR /app
COPY storefront/package.json storefront/package-lock.json ./
RUN npm ci

COPY storefront/ ./
ARG VITE_MERCHANT_API_URL
ENV VITE_MERCHANT_API_URL=$VITE_MERCHANT_API_URL
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY storefront/Caddyfile /etc/caddy/Caddyfile
