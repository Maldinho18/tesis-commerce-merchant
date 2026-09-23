import { Search, Store, X } from "lucide-react"

import { CATEGORY_LABELS } from "@/lib/catalog"
import { cn } from "cn"

/**
 * Cabecera de la tienda. El kit apila tres barras; aquí se consolida en una sola fila
 * con la navegación debajo, para que la retícula empiece más arriba y respire.
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
    <header className="sticky top-0 z-40 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex w-full max-w-7xl items-center gap-8 px-6 py-4">
        <a href="/" className="flex shrink-0 items-center gap-2.5">
          <Store className="size-5 text-primary" strokeWidth={2} />
          <span className="text-[0.95rem] font-semibold tracking-tight">Tesis Commerce</span>
        </a>

        <div className="relative min-w-0 max-w-xl flex-1">
          <Search
            className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-gray-400"
            aria-hidden
          />
          <input
            type="search"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Buscar productos y marcas"
            aria-label="Buscar en el catálogo"
            className="h-10 w-full rounded-full bg-muted pr-9 pl-10 text-sm outline-none transition-colors placeholder:text-gray-400 focus-visible:bg-background focus-visible:ring-2 focus-visible:ring-foreground/10"
          />
          {query && (
            <button
              type="button"
              onClick={() => onQuery("")}
              aria-label="Limpiar búsqueda"
              className="absolute top-1/2 right-3.5 -translate-y-1/2 text-gray-400 transition-colors hover:text-foreground"
            >
              <X className="size-4" />
            </button>
          )}
        </div>

        <div className="ml-auto hidden items-center gap-4 lg:flex">
          <span className="text-xs text-gray-500">
            {productCount.toLocaleString("es-CO")} productos
          </span>
          <span className="rounded-full bg-accent/10 px-2.5 py-1 text-[0.7rem] font-medium text-accent">
            Solo consulta
          </span>
        </div>
      </div>

      <nav
        className="mx-auto flex w-full max-w-7xl gap-1 overflow-x-auto px-6 pb-2"
        aria-label="Categorías"
      >
        <CategoryLink active={category === null} onClick={() => onCategory(null)}>
          Todo
        </CategoryLink>
        {categories.map((value) => (
          <CategoryLink key={value} active={category === value} onClick={() => onCategory(value)}>
            {CATEGORY_LABELS[value] ?? value}
          </CategoryLink>
        ))}
      </nav>
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
        "shrink-0 rounded-full px-3.5 py-1.5 text-sm whitespace-nowrap transition-colors",
        active
          ? "bg-foreground font-medium text-background"
          : "text-gray-600 hover:bg-muted hover:text-foreground"
      )}
    >
      {children}
    </button>
  )
}
