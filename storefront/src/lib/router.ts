import { useEffect, useState } from "react"

export type Route = { name: "list" } | { name: "product"; id: string }

const PRODUCT_PREFIX = "/producto/"

export function parseRoute(pathname: string): Route {
  if (pathname.startsWith(PRODUCT_PREFIX)) {
    const id = decodeURIComponent(pathname.slice(PRODUCT_PREFIX.length))
    if (id) return { name: "product", id }
  }
  return { name: "list" }
}

export function productPath(id: string): string {
  return `${PRODUCT_PREFIX}${encodeURIComponent(id)}`
}

export function navigate(path: string) {
  if (path === window.location.pathname) return
  window.history.pushState({}, "", path)
  window.dispatchEvent(new PopStateEvent("popstate"))
}

/**
 * Enrutado mínimo sobre la History API: cada producto tiene URL propia y compartible, y
 * atrás/adelante del navegador funcionan. Caddy ya devuelve index.html para rutas
 * desconocidas, así que recargar una URL de producto entra directo a su página.
 */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname))
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.pathname))
    window.addEventListener("popstate", onChange)
    return () => window.removeEventListener("popstate", onChange)
  }, [])
  return route
}
