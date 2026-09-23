import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
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
  conditions,
  budgets,
  currency,
  onChange,
}: {
  filters: Filters
  categories: string[]
  brands: string[]
  conditions: string[]
  budgets: number[]
  currency: string
  onChange: (next: Filters) => void
}) {
  const count = activeFilterCount(filters)

  return (
    <div className="flex flex-col gap-3 border-b border-border pb-4">
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
        {brands.map((brand) => (
          <Chip key={brand} active={filters.brand === brand} onClick={() => onChange({ ...filters, brand })}>
            {brand}
          </Chip>
        ))}
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
