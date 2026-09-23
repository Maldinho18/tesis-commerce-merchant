# Build estático del storefront servido por Caddy.
# `VITE_MERCHANT_API_URL` se inlinea en tiempo de build, igual que en la UI del agente.
FROM node:24-slim AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ARG VITE_MERCHANT_API_URL
ENV VITE_MERCHANT_API_URL=$VITE_MERCHANT_API_URL
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
