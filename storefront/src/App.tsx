import { useEffect, useMemo, useState } from "react"
import { Store } from "lucide-react"

import { Button } from "@/components/ui/button"
import { FilterBar } from "@/components/storefront/filters"
import { EMPTY_FILTERS, budgetSteps, matchesFilters, type Filters } from "@/lib/filters"
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
    const brands = new Set<string>()
    const conditions = new Set<string>()
    for (const product of products) {
      for (const category of categoriesOf(product)) categories.add(category)
      for (const condition of conditionsOf(product)) conditions.add(condition)
      brands.add(brandOf(product))
    }
    return {
      categories: [...categories].sort(),
      brands: [...brands].sort(),
      conditions: [...conditions].sort(),
      budgets: budgetSteps(products),
    }
  }, [products])

  const visible = useMemo(
    () => products.filter((product) => matchesFilters(product, filters)),
    [products, filters]
  )

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
            conditions={facets.conditions}
            budgets={facets.budgets}
            currency={currency}
            onChange={setFilters}
          />

          {visible.length === 0 ? (
            <div className="rounded-lg bg-muted px-4 py-10 text-center">
              <p className="text-sm font-medium">Ningún producto cumple esos filtros.</p>
              <Button variant="outline" size="sm" className="mt-3" onClick={() => setFilters(EMPTY_FILTERS)}>
                Limpiar filtros
              </Button>
            </div>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                {visible.length} de {products.length} productos
              </p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                {visible.map((product) => (
                  <ProductCard key={product.id} product={product} onOpen={setOpenProduct} />
                ))}
              </div>
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
