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

Servicio propio en Railway con `rootDirectory` en `storefront`, igual que la UI del agente vive
en `ui/` dentro del repositorio del comprador. El `Dockerfile` compila con Vite y sirve el
resultado con Caddy en `0.0.0.0:${PORT:-8080}`.
