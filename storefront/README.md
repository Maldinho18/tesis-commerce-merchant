# Tesis Commerce Storefront

Vitrina humana del comercio sintético. Es **solo de consulta**: lee el catálogo por
`GET /storefront/catalog` del merchant y no expone carrito ni checkout.

La compra ocurre exclusivamente por el canal ACP, que atiende al agente comprador con su propio
Bearer. Un catálogo autoritativo, dos canales: HTML para personas y ACP para el agente. El
endpoint devuelve la misma proyección que consume el comprador y la lee en vivo de la base, así
que el inventario que ve una persona ya refleja lo que compró el agente.

## Desarrollo

```sh
npm install
cp -n .env.example .env
npm run dev      # 127.0.0.1:5174
npm run lint
npm run build
```

`VITE_MERCHANT_API_URL` apunta al origen público del merchant. El merchant debe declarar ese
mismo origen en `STOREFRONT_ORIGIN` para habilitarlo en CORS; sin eso el navegador bloquea la
lectura del catálogo.

## Despliegue

Servicio propio en Railway sobre este mismo repositorio. El servicio se selecciona con la
variable `RAILWAY_DOCKERFILE_PATH=storefront/Dockerfile`, así que **el contexto de build es la
raíz del repositorio** y los `COPY` del Dockerfile llevan el prefijo `storefront/`. En local:

```sh
docker build -f storefront/Dockerfile .
```

Con esa variable el servicio sigue leyendo el `railway.json` de la raíz, que es el del merchant
y apunta el healthcheck a `/health/ready`; por eso el Caddyfile responde esa ruta. La
alternativa más limpia es fijar *Root Directory* en `storefront` desde el panel de Railway, que
además haría que se leyera el `railway.json` de esta carpeta.

El `Dockerfile` compila con Vite y sirve el resultado con Caddy en `0.0.0.0:${PORT:-8080}`.
