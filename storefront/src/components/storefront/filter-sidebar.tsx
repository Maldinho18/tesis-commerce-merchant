import { Button } from "@/components/ui/button"
import { CONDITION_LABELS, formatMoney } from "@/lib/catalog"
import { EMPTY_FILTERS, activeFilterCount, type Filters } from "@/lib/filters"
import { cn } from "cn"

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border py-4 first:pt-0 last:border-b-0">
      <h3 className="mb-2.5 text-xs font-semibold tracking-wide text-foreground uppercase">
        {title}
      </h3>
      {children}
    </section>
  )
}

function Option({
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
        "-mx-2 block w-[calc(100%+1rem)] rounded-md px-2 py-1 text-left text-sm transition-colors",
        active
          ? "bg-accent font-medium text-accent-foreground"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {children}
    </button>
  )
}

/**
 * Columna de filtros. Refleja uno a uno las restricciones duras del comprador: marca,
 * precio, condición y disponibilidad. La categoría vive en la navegación superior.
 */
export function FilterSidebar({
  filters,
  brands,
  topBrands,
  conditions,
  budgets,
  currency,
  onChange,
}: {
  filters: Filters
  brands: string[]
  topBrands: string[]
  conditions: string[]
  budgets: number[]
  currency: string
  onChange: (next: Filters) => void
}) {
  const count = activeFilterCount(filters)

  return (
    <div className="flex flex-col">
      <div className="flex items-center justify-between pb-3">
        <h2 className="text-sm font-semibold">Filtros</h2>
        {count > 0 && (
          <Button variant="ghost" size="xs" onClick={() => onChange(EMPTY_FILTERS)}>
            Limpiar ({count})
          </Button>
        )}
      </div>

      <Section title="Marca">
        <div className="flex flex-col gap-0.5">
          <Option active={filters.brand === null} onClick={() => onChange({ ...filters, brand: null })}>
            Todas las marcas
          </Option>
          {topBrands.map((brand) => (
            <Option
              key={brand}
              active={filters.brand === brand}
              onClick={() => onChange({ ...filters, brand })}
            >
              {brand}
            </Option>
          ))}
        </div>
        {brands.length > topBrands.length && (
          <select
            value={filters.brand && !topBrands.includes(filters.brand) ? filters.brand : ""}
            onChange={(event) => onChange({ ...filters, brand: event.target.value || null })}
            aria-label="Todas las marcas"
            className="mt-2 h-8 w-full rounded-md border border-border bg-background px-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <option value="">Otra marca…</option>
            {brands.map((brand) => (
              <option key={brand} value={brand}>
                {brand}
              </option>
            ))}
          </select>
        )}
      </Section>

      <Section title="Precio">
        <div className="flex flex-col gap-0.5">
          <Option
            active={filters.maxAmount === null}
            onClick={() => onChange({ ...filters, maxAmount: null })}
          >
            Cualquier precio
          </Option>
          {budgets.map((amount) => (
            <Option
              key={amount}
              active={filters.maxAmount === amount}
              onClick={() => onChange({ ...filters, maxAmount: amount })}
            >
              Hasta {formatMoney(amount, currency)}
            </Option>
          ))}
        </div>
      </Section>

      <Section title="Condición">
        <div className="flex flex-col gap-0.5">
          <Option
            active={filters.condition === null}
            onClick={() => onChange({ ...filters, condition: null })}
          >
            Cualquiera
          </Option>
          {conditions.map((condition) => (
            <Option
              key={condition}
              active={filters.condition === condition}
              onClick={() => onChange({ ...filters, condition })}
            >
              {CONDITION_LABELS[condition] ?? condition}
            </Option>
          ))}
        </div>
      </Section>

      <Section title="Disponibilidad">
        <Option
          active={filters.onlyAvailable}
          onClick={() => onChange({ ...filters, onlyAvailable: !filters.onlyAvailable })}
        >
          Solo productos disponibles
        </Option>
      </Section>
    </div>
  )
}
