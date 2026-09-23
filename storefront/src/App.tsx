import { useEffect, useMemo, useState } from "react"
import { Store } from "lucide-react"

import { Button } from "@/components/ui/button"
import { FilterBar } from "@/components/storefront/filters"
import {
  EMPTY_FILTERS,
  PAGE_SIZE,
  budgetSteps,
  matchesFilters,
  type Filters,
} from "@/lib/filters"
import { ProductCard } from "@/components/storefront/product-card"
import { ProductDetail } from "@/components/storefront/product-detail"
import {
  MERCHANT_ORIGIN,
  brandOf,
  categoriesOf,
  conditionsOf,
  fetchCatalog,
  type Catalog,
  type FeedProduct,
} from "@/lib/catalog"

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [openProduct, setOpenProduct] = useState<FeedProduct | null>(null)
  const [page, setPage] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchCatalog(controller.signal)
      .then(setCatalog)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : "No se pudo cargar el catálogo")
      })
    return () => controller.abort()
  }, [])

  // Sin memoizar, el arreglo cambia en cada render y anula los useMemo de abajo.
  const products = useMemo(() => catalog?.products ?? [], [catalog])

  const facets = useMemo(() => {
    const categories = new Set<string>()
    const brands = new Map<string, number>()
    const conditions = new Set<string>()
    for (const product of products) {
      for (const category of categoriesOf(product)) categories.add(category)
      for (const condition of conditionsOf(product)) conditions.add(condition)
      const brand = brandOf(product)
      brands.set(brand, (brands.get(brand) ?? 0) + 1)
    }
    return {
      categories: [...categories].sort(),
      brands: [...brands.keys()].sort(),
      // Las marcas con más productos son las que valen un chip.
      topBrands: [...brands.entries()]
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .slice(0, 12)
        .map(([brand]) => brand)
        .sort(),
      conditions: [...conditions].sort(),
      budgets: budgetSteps(products),
    }
  }, [products])

  const visible = useMemo(
    () => products.filter((product) => matchesFilters(product, filters)),
    [products, filters]
  )

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE))
  // Al cambiar los filtros la página actual puede quedar fuera de rango.
  const current = Math.min(page, pageCount - 1)
  const shown = useMemo(
    () => visible.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE),
    [visible, current]
  )

  function applyFilters(next: Filters) {
    setFilters(next)
    setPage(0)
  }

  const currency = products[0]?.variants[0]?.price.currency ?? "COP"
  const skuCount = products.reduce((total, product) => total + product.variants.length, 0)

  return (
    <div className="mx-auto flex min-h-svh w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Store className="size-5 text-primary" />
            <h1 className="text-lg font-semibold tracking-tight">Tesis Commerce</h1>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Catálogo sintético de tecnología. Entrega en Bogotá, precios en pesos colombianos.
          </p>
        </div>
        {catalog && (
          <p className="text-xs text-muted-foreground">
            {products.length} productos · {skuCount} referencias
          </p>
        )}
      </header>

      {error && (
        <div className="rounded-lg bg-destructive/10 px-4 py-3 text-sm text-destructive">
          <p className="font-medium">No se pudo cargar el catálogo.</p>
          <p className="mt-1 text-xs">
            {error} — se consultó {MERCHANT_ORIGIN}/storefront/catalog
          </p>
        </div>
      )}

      {!catalog && !error && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, index) => (
            <div key={index} className="h-72 animate-pulse rounded-xl bg-muted" />
          ))}
        </div>
      )}

      {catalog && (
        <>
          <FilterBar
            filters={filters}
            categories={facets.categories}
            brands={facets.brands}
            topBrands={facets.topBrands}
            conditions={facets.conditions}
            budgets={facets.budgets}
            currency={currency}
            onChange={applyFilters}
          />

          {visible.length === 0 ? (
            <div className="rounded-lg bg-muted px-4 py-10 text-center">
              <p className="text-sm font-medium">Ningún producto cumple esos filtros.</p>
              <Button variant="outline" size="sm" className="mt-3" onClick={() => applyFilters(EMPTY_FILTERS)}>
                Limpiar filtros
              </Button>
            </div>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {visible.length.toLocaleString("es-CO")} de{" "}
                {products.length.toLocaleString("es-CO")} productos
                {pageCount > 1 && ` · página ${current + 1} de ${pageCount}`}
              </p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {shown.map((product) => (
                  <ProductCard key={product.id} product={product} onOpen={setOpenProduct} />
                ))}
              </div>
              {pageCount > 1 && (
                <nav className="flex items-center justify-center gap-2" aria-label="Paginación">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={current === 0}
                    onClick={() => setPage(current - 1)}
                  >
                    Anterior
                  </Button>
                  <span className="text-xs tabular-nums text-muted-foreground">
                    {current + 1} / {pageCount}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={current >= pageCount - 1}
                    onClick={() => setPage(current + 1)}
                  >
                    Siguiente
                  </Button>
                </nav>
              )}
            </>
          )}
        </>
      )}

      <footer className="mt-auto border-t border-border pt-4 text-xs text-muted-foreground">
        Vitrina de solo consulta para la tesis. El catálogo lo sirve el comercio y es el mismo que
        consume el agente comprador por ACP; la compra nunca ocurre por aquí.
      </footer>

      {openProduct && (
        <ProductDetail product={openProduct} onClose={() => setOpenProduct(null)} />
      )}
    </div>
  )
}
