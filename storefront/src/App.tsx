import { useEffect, useMemo, useState } from "react"
import { SlidersHorizontal } from "lucide-react"

import { Button } from "@/components/ui/button"
import { FilterSidebar } from "@/components/storefront/filter-sidebar"
import { ProductCard } from "@/components/storefront/product-card"
import { ProductDetail } from "@/components/storefront/product-detail"
import { SiteHeader } from "@/components/storefront/site-header"
import { navigate, productPath, useRoute } from "@/lib/router"
import {
  CATEGORY_LABELS,
  MERCHANT_ORIGIN,
  brandOf,
  categoriesOf,
  conditionsOf,
  fetchCatalog,
  type Catalog,
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
  const [page, setPage] = useState(0)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const route = useRoute()

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

  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [route])

  const currency = products[0]?.variants[0]?.price.currency ?? "COP"
  const routedProduct =
    route.name === "product"
      ? (products.find((product) => product.id === route.id) ?? null)
      : null

  const heading = filters.category
    ? (CATEGORY_LABELS[filters.category] ?? filters.category)
    : "Todo el catálogo"

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <SiteHeader
        query={filters.query}
        category={filters.category}
        categories={facets.categories}
        productCount={products.length}
        onQuery={(query) => applyFilters({ ...filters, query })}
        onCategory={(category) => applyFilters({ ...filters, category })}
      />

      {routedProduct ? (
        <ProductDetail product={routedProduct} onBack={() => navigate("/")} />
      ) : route.name === "product" && catalog ? (
        <div className="mx-auto w-full max-w-7xl flex-1 px-4 py-16 text-center sm:px-6">
          <p className="text-sm font-medium">Ese producto no está en el catálogo.</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => navigate("/")}>
            Volver al catálogo
          </Button>
        </div>
      ) : (
        <>
      <nav
          className="mx-auto w-full max-w-7xl px-4 pt-4 text-xs text-gray-600 sm:px-6"
          aria-label="Ruta"
        >
          <ol className="flex flex-wrap items-center gap-1.5">
            <li>Inicio</li>
            <li aria-hidden>›</li>
            <li>Catálogo</li>
            <li aria-hidden>›</li>
            <li className="font-medium text-foreground">{heading}</li>
          </ol>
        </nav>
  
        <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-4 pb-10 sm:px-6">
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
                className={`${filtersOpen ? "block" : "hidden"} w-64 shrink-0 lg:block`}
                aria-label="Filtros"
              >
                <div className="sticky top-40 border border-border bg-card px-4 py-3">
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
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border border-border bg-gray-50 px-4 py-2.5">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h1 className="text-base font-semibold tracking-tight">{heading}</h1>
                    <p className="text-xs text-gray-600">
                      Mostrando{" "}
                      {visible.length === 0
                        ? 0
                        : (current * PAGE_SIZE + 1).toLocaleString("es-CO")}
                      –
                      {Math.min((current + 1) * PAGE_SIZE, visible.length).toLocaleString("es-CO")} de{" "}
                      {visible.length.toLocaleString("es-CO")} productos
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
                  <div className="border border-border bg-card px-4 py-16 text-center">
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
                        <ProductCard
                          key={product.id}
                          product={product}
                          onOpen={(item) => navigate(productPath(item.id))}
                        />
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
  
          </>
      )}

      <footer className="bg-gray-900 text-gray-300">
        <div className="mx-auto grid w-full max-w-7xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-4">
          <div className="md:col-span-2">
            <p className="text-base font-bold text-primary-foreground">TESIS COMMERCE</p>
            <p className="mt-2 max-w-md text-xs leading-relaxed">
              Vitrina de solo consulta. El catálogo lo sirve el comercio y es el mismo que consume
              el agente comprador por ACP; la compra nunca ocurre por aquí.
            </p>
          </div>
          <div>
            <p className="text-xs font-semibold tracking-wide text-primary-foreground uppercase">
              Categorías
            </p>
            <ul className="mt-3 space-y-1.5 text-xs">
              {facets.categories.map((value) => (
                <li key={value}>
                  <button
                    type="button"
                    onClick={() => applyFilters({ ...filters, category: value })}
                    className="hover:text-primary-foreground"
                  >
                    {CATEGORY_LABELS[value] ?? value}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-xs font-semibold tracking-wide text-primary-foreground uppercase">
              Procedencia
            </p>
            <ul className="mt-3 space-y-1.5 text-xs">
              <li>Datos e imágenes: Wikidata</li>
              <li>Fotografías: Wikimedia Commons</li>
              <li>Inventario y precios: sintéticos</li>
              <li>Protocolo: ACP 2026-04-17</li>
            </ul>
          </div>
        </div>
      </footer>

    </div>
  )
}
