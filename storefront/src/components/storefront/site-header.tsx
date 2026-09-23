import { ChevronDown, Search, Store, X } from "lucide-react"

import { CATEGORY_LABELS } from "@/lib/catalog"
import { cn } from "cn"

/**
 * Cabecera de la tienda, siguiendo el kit de Figma: franja utilitaria oscura, cabecera
 * blanca con buscador dominante y una fila de navegación por categoría.
 */
export function SiteHeader({
  query,
  category,
  categories,
  productCount,
  onQuery,
  onCategory,
}: {
  query: string
  category: string | null
  categories: string[]
  productCount: number
  onQuery: (value: string) => void
  onCategory: (value: string | null) => void
}) {
  return (
    <header className="sticky top-0 z-40">
      <div className="bg-gray-900 text-[0.7rem] text-gray-300">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-4 py-1.5 sm:px-6">
          <p>Catálogo sintético de la tesis · Entrega en Bogotá</p>
          <p className="hidden sm:block">
            Precios en pesos colombianos · {productCount.toLocaleString("es-CO")} productos
          </p>
        </div>
      </div>

      <div className="border-b border-border bg-background">
        <div className="mx-auto flex w-full max-w-7xl items-center gap-6 px-4 py-3 sm:px-6">
          <a href="/" className="flex shrink-0 items-center gap-2">
            <Store className="size-6 text-primary" />
            <span className="text-lg font-bold tracking-tight">TESIS COMMERCE</span>
          </a>

          <div className="relative min-w-0 flex-1">
            <Search
              className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-gray-400"
              aria-hidden
            />
            <input
              type="search"
              value={query}
              onChange={(event) => onQuery(event.target.value)}
              placeholder="Buscar productos, marcas y más…"
              aria-label="Buscar en el catálogo"
              className="h-10 w-full rounded-sm border border-border bg-background pr-9 pl-10 text-sm outline-none placeholder:text-gray-400 focus-visible:border-primary focus-visible:ring-2 focus-visible:ring-primary/25"
            />
            {query && (
              <button
                type="button"
                onClick={() => onQuery("")}
                aria-label="Limpiar búsqueda"
                className="absolute top-1/2 right-3 -translate-y-1/2 text-gray-400 hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            )}
          </div>

          <span className="hidden shrink-0 rounded-sm bg-accent/10 px-2.5 py-1 text-[0.7rem] font-semibold text-accent lg:block">
            Solo consulta
          </span>
        </div>
      </div>

      <div className="border-b border-border bg-gray-900">
        <nav
          className="mx-auto flex w-full max-w-7xl gap-1 overflow-x-auto px-4 sm:px-6"
          aria-label="Categorías"
        >
          <CategoryLink active={category === null} onClick={() => onCategory(null)}>
            Todo el catálogo
          </CategoryLink>
          {categories.map((value) => (
            <CategoryLink key={value} active={category === value} onClick={() => onCategory(value)}>
              {CATEGORY_LABELS[value] ?? value}
              <ChevronDown className="size-3.5 opacity-60" aria-hidden />
            </CategoryLink>
          ))}
        </nav>
      </div>
    </header>
  )
}

function CategoryLink({
  active,
  children,
  onClick,
}: {
  active: boolean
  children: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex shrink-0 items-center gap-1 px-3 py-2.5 text-[0.8rem] whitespace-nowrap transition-colors",
        active
          ? "font-semibold text-primary-foreground shadow-[inset_0_-2px_0_var(--primary)]"
          : "text-gray-300 hover:text-primary-foreground"
      )}
    >
      {children}
    </button>
  )
}
