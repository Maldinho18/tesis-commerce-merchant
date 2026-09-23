import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Search } from "lucide-react"
import { cn } from "cn"
import { CATEGORY_LABELS, CONDITION_LABELS, formatMoney } from "@/lib/catalog"
import { EMPTY_FILTERS, activeFilterCount, type Filters } from "@/lib/filters"

function Chip({
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
      aria-pressed={active}
      className={cn(
        "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
        active
          ? "border-transparent bg-primary text-primary-foreground"
          : "border-border bg-background text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {children}
    </button>
  )
}

/**
 * Los controles reflejan uno a uno las restricciones duras del comprador: categoría, marca,
 * condición, tope de precio y disponibilidad. Es el mismo filtro, por el canal humano.
 */
export function FilterBar({
  filters,
  categories,
  brands,
  topBrands,
  conditions,
  budgets,
  currency,
  onChange,
}: {
  filters: Filters
  categories: string[]
  brands: string[]
  topBrands: string[]
  conditions: string[]
  budgets: number[]
  currency: string
  onChange: (next: Filters) => void
}) {
  const count = activeFilterCount(filters)

  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4">
      <div className="relative">
        <Search
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <input
          type="search"
          value={filters.query}
          onChange={(event) => onChange({ ...filters, query: event.target.value })}
          placeholder="Buscar por modelo, marca o característica…"
          aria-label="Buscar en el catálogo"
          className="h-10 w-full rounded-lg border border-border bg-background pr-3 pl-9 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
        />
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-muted-foreground">Categoría</span>
        <Chip active={filters.category === null} onClick={() => onChange({ ...filters, category: null })}>
          Todas
        </Chip>
        {categories.map((category) => (
          <Chip
            key={category}
            active={filters.category === category}
            onClick={() => onChange({ ...filters, category })}
          >
            {CATEGORY_LABELS[category] ?? category}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-muted-foreground">Marca</span>
        <Chip active={filters.brand === null} onClick={() => onChange({ ...filters, brand: null })}>
          Todas
        </Chip>
        {/* Solo las marcas frecuentes caben como chips; con cientos de marcas el resto
            se elige en el desplegable, que siempre las lista todas. */}
        {topBrands.map((brand) => (
          <Chip
            key={brand}
            active={filters.brand === brand}
            onClick={() => onChange({ ...filters, brand })}
          >
            {brand}
          </Chip>
        ))}
        {brands.length > topBrands.length && (
          <select
            value={filters.brand && !topBrands.includes(filters.brand) ? filters.brand : ""}
            onChange={(event) =>
              onChange({ ...filters, brand: event.target.value || null })
            }
            aria-label="Todas las marcas"
            className="h-7 rounded-full border border-border bg-background px-2.5 text-xs text-muted-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="">Otra marca…</option>
            {brands.map((brand) => (
              <option key={brand} value={brand}>
                {brand}
              </option>
            ))}
          </select>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-muted-foreground">Hasta</span>
        <Chip
          active={filters.maxAmount === null}
          onClick={() => onChange({ ...filters, maxAmount: null })}
        >
          Sin tope
        </Chip>
        {budgets.map((amount) => (
          <Chip
            key={amount}
            active={filters.maxAmount === amount}
            onClick={() => onChange({ ...filters, maxAmount: amount })}
          >
            {formatMoney(amount, currency)}
          </Chip>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs font-medium text-muted-foreground">Condición</span>
        <Chip
          active={filters.condition === null}
          onClick={() => onChange({ ...filters, condition: null })}
        >
          Cualquiera
        </Chip>
        {conditions.map((condition) => (
          <Chip
            key={condition}
            active={filters.condition === condition}
            onClick={() => onChange({ ...filters, condition })}
          >
            {CONDITION_LABELS[condition] ?? condition}
          </Chip>
        ))}
        <span className="mx-2 h-4 w-px bg-border" aria-hidden />
        <Chip
          active={filters.onlyAvailable}
          onClick={() => onChange({ ...filters, onlyAvailable: !filters.onlyAvailable })}
        >
          Solo disponibles
        </Chip>

        {count > 0 && (
          <>
            <span className="mx-1 h-4 w-px bg-border" aria-hidden />
            <Badge variant="muted">{count} activos</Badge>
            <Button variant="ghost" size="xs" onClick={() => onChange(EMPTY_FILTERS)}>
              Limpiar
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
