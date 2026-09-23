import { useEffect, useMemo, useState } from "react"
import { SlidersHorizontal } from "lucide-react"

import { Button } from "@/components/ui/button"
import { FilterSidebar } from "@/components/storefront/filter-sidebar"
import { ProductCard } from "@/components/storefront/product-card"
import { ProductDetail } from "@/components/storefront/product-detail"
import { SiteHeader } from "@/components/storefront/site-header"
import {
  CATEGORY_LABELS,
  MERCHANT_ORIGIN,
  brandOf,
  categoriesOf,
  conditionsOf,
  fetchCatalog,
  type Catalog,
  type FeedProduct,
} from "@/lib/catalog"
import {
  EMPTY_FILTERS,
  PAGE_SIZE,
  SORT_LABELS,
  budgetSteps,
  matchesFilters,
  sortProducts,
  type Filters,
  type SortKey,
} from "@/lib/filters"

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<SortKey>("relevance")
  const [openProduct, setOpenProduct] = useState<FeedProduct | null>(null)
  const [page, setPage] = useState(0)
  const [filtersOpen, setFiltersOpen] = useState(false)

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
      // Las marcas con más productos son las que valen un lugar fijo en la columna.
      topBrands: [...brands.entries()]
        .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
        .slice(0, 10)
        .map(([brand]) => brand)
        .sort(),
      conditions: [...conditions].sort(),
      budgets: budgetSteps(products),
    }
  }, [products])

  const visible = useMemo(
    () => sortProducts(products.filter((product) => matchesFilters(product, filters)), sort),
    [products, filters, sort]
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
  const heading = filters.category
    ? (CATEGORY_LABELS[filters.category] ?? filters.category)
    : "Todo el catálogo"

  return (
    <div className="flex min-h-svh flex-col bg-secondary/30">
      <SiteHeader
        query={filters.query}
        category={filters.category}
        categories={facets.categories}
        productCount={products.length}
        onQuery={(query) => applyFilters({ ...filters, query })}
        onCategory={(category) => applyFilters({ ...filters, category })}
      />

      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6">
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
              <div key={index} className="h-80 animate-pulse rounded-xl bg-muted" />
            ))}
          </div>
        )}

        {catalog && (
          <div className="flex gap-6">
            <aside
              className={`${filtersOpen ? "block" : "hidden"} w-60 shrink-0 lg:block`}
              aria-label="Filtros"
            >
              <div className="sticky top-32 rounded-xl border border-border bg-card p-4">
                <FilterSidebar
                  filters={filters}
                  brands={facets.brands}
                  topBrands={facets.topBrands}
                  conditions={facets.conditions}
                  budgets={facets.budgets}
                  currency={currency}
                  onChange={applyFilters}
                />
              </div>
            </aside>

            <div className="min-w-0 flex-1">
              <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h1 className="text-xl font-semibold tracking-tight">{heading}</h1>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {visible.length.toLocaleString("es-CO")} resultados
                    {pageCount > 1 && ` · página ${current + 1} de ${pageCount}`}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="lg:hidden"
                    onClick={() => setFiltersOpen((open) => !open)}
                  >
                    <SlidersHorizontal />
                    Filtros
                  </Button>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    Ordenar
                    <select
                      value={sort}
                      onChange={(event) => {
                        setSort(event.target.value as SortKey)
                        setPage(0)
                      }}
                      className="h-8 rounded-md border border-border bg-background px-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      {Object.entries(SORT_LABELS).map(([key, label]) => (
                        <option key={key} value={key}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
              </div>

              {visible.length === 0 ? (
                <div className="rounded-xl border border-border bg-card px-4 py-16 text-center">
                  <p className="text-sm font-medium">Ningún producto cumple esos filtros.</p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-3"
                    onClick={() => applyFilters(EMPTY_FILTERS)}
                  >
                    Limpiar filtros
                  </Button>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 gap-4 lg:grid-cols-3 xl:grid-cols-4">
                    {shown.map((product) => (
                      <ProductCard key={product.id} product={product} onOpen={setOpenProduct} />
                    ))}
                  </div>

                  {pageCount > 1 && (
                    <nav
                      className="mt-6 flex items-center justify-center gap-2"
                      aria-label="Paginación"
                    >
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
            </div>
          </div>
        )}
      </main>

      <footer className="border-t border-border bg-background">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 text-xs text-muted-foreground sm:px-6">
          <p className="font-medium text-foreground">Tesis Commerce</p>
          <p className="mt-1 max-w-2xl">
            Vitrina de solo consulta para la tesis. El catálogo lo sirve el comercio y es el mismo
            que consume el agente comprador por ACP; la compra nunca ocurre por aquí.
          </p>
          <p className="mt-2">
            Datos e imágenes de productos provenientes de Wikidata y Wikimedia Commons.
          </p>
        </div>
      </footer>

      {openProduct && <ProductDetail product={openProduct} onClose={() => setOpenProduct(null)} />}
    </div>
  )
}
