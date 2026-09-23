import { Search, Store, X } from "lucide-react"

import { CATEGORY_LABELS } from "@/lib/catalog"
import { cn } from "cn"

/** Barra superior de la tienda: identidad, buscador y navegación por categoría. */
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
    <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-3 px-4 py-3 sm:px-6">
        <div className="flex items-center gap-4">
          <a href="/" className="flex shrink-0 items-center gap-2">
            <Store className="size-5 text-primary" />
            <span className="text-base font-semibold tracking-tight">Tesis Commerce</span>
          </a>

          <div className="relative min-w-0 flex-1">
            <Search
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <input
              type="search"
              value={query}
              onChange={(event) => onQuery(event.target.value)}
              placeholder="Buscar productos, marcas y más…"
              aria-label="Buscar en el catálogo"
              className="h-10 w-full rounded-full border border-border bg-secondary/50 pr-9 pl-9 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:bg-background focus-visible:ring-3 focus-visible:ring-ring/50"
            />
            {query && (
              <button
                type="button"
                onClick={() => onQuery("")}
                aria-label="Limpiar búsqueda"
                className="absolute top-1/2 right-3 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              >
                <X className="size-4" />
              </button>
            )}
          </div>

          <span className="hidden shrink-0 text-xs text-muted-foreground sm:block">
            {productCount.toLocaleString("es-CO")} productos
          </span>
        </div>

        <nav className="-mx-1 flex gap-1 overflow-x-auto px-1" aria-label="Categorías">
          <CategoryLink active={category === null} onClick={() => onCategory(null)}>
            Todo
          </CategoryLink>
          {categories.map((value) => (
            <CategoryLink
              key={value}
              active={category === value}
              onClick={() => onCategory(value)}
            >
              {CATEGORY_LABELS[value] ?? value}
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
        "relative shrink-0 px-3 py-1.5 text-sm whitespace-nowrap transition-colors",
        active
          ? "font-medium text-foreground after:absolute after:inset-x-3 after:-bottom-px after:h-0.5 after:rounded-full after:bg-primary"
          : "text-muted-foreground hover:text-foreground"
      )}
    >
      {children}
    </button>
  )
}
