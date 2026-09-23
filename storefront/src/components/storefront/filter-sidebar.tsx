import { useState } from "react"
import { Minus, Plus } from "lucide-react"

import { CONDITION_LABELS, formatMoney } from "@/lib/catalog"
import { EMPTY_FILTERS, activeFilterCount, type Filters } from "@/lib/filters"
import { cn } from "cn"

/** Sección plegable, como los acordeones de filtro del kit. */
function Section({
  title,
  children,
  defaultOpen = true,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border-t border-border first:border-t-0">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center justify-between py-3.5 text-left"
      >
        <span className="text-[0.8rem] font-medium">{title}</span>
        {open ? (
          <Minus className="size-4 text-gray-500" aria-hidden />
        ) : (
          <Plus className="size-4 text-gray-500" aria-hidden />
        )}
      </button>
      {open && <div className="pb-4">{children}</div>}
    </section>
  )
}

/** Opción con casilla, como en el kit: la marca de verificación va a la izquierda. */
function Check({
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
      className="flex w-full items-center gap-2.5 py-1.5 text-left text-sm"
    >
      <span
        className={cn(
          "grid size-4 shrink-0 place-items-center rounded-[3px] border transition-colors",
          active ? "border-foreground bg-foreground" : "border-gray-300 bg-background"
        )}
        aria-hidden
      >
        {active && (
          <svg viewBox="0 0 10 8" className="size-2.5 fill-none stroke-white stroke-2">
            <path d="M1 4l2.5 2.5L9 1" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </span>
      <span className={cn("truncate", active ? "text-foreground" : "text-gray-600")}>
        {children}
      </span>
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
      <div className="flex items-center justify-between pb-1">
        <h2 className="text-sm font-semibold">Filtros</h2>
        {count > 0 && (
          <button
            type="button"
            onClick={() => onChange(EMPTY_FILTERS)}
            className="text-xs font-medium text-primary hover:underline"
          >
            Limpiar ({count})
          </button>
        )}
      </div>

      <Section title="Marca">
        <div className="flex flex-col">
          {topBrands.map((brand) => (
            <Check
              key={brand}
              active={filters.brand === brand}
              onClick={() => onChange({ ...filters, brand: filters.brand === brand ? null : brand })}
            >
              {brand}
            </Check>
          ))}
        </div>
        {brands.length > topBrands.length && (
          <select
            value={filters.brand && !topBrands.includes(filters.brand) ? filters.brand : ""}
            onChange={(event) => onChange({ ...filters, brand: event.target.value || null })}
            aria-label="Todas las marcas"
            className="mt-2 h-9 w-full rounded-lg bg-muted px-2.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-foreground/10"
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

      <Section title="Rango de precio">
        <div className="flex flex-col">
          {budgets.map((amount) => (
            <Check
              key={amount}
              active={filters.maxAmount === amount}
              onClick={() =>
                onChange({ ...filters, maxAmount: filters.maxAmount === amount ? null : amount })
              }
            >
              Hasta {formatMoney(amount, currency)}
            </Check>
          ))}
        </div>
      </Section>

      <Section title="Condición">
        <div className="flex flex-col">
          {conditions.map((condition) => (
            <Check
              key={condition}
              active={filters.condition === condition}
              onClick={() =>
                onChange({
                  ...filters,
                  condition: filters.condition === condition ? null : condition,
                })
              }
            >
              {CONDITION_LABELS[condition] ?? condition}
            </Check>
          ))}
        </div>
      </Section>

      <Section title="Disponibilidad">
        <Check
          active={filters.onlyAvailable}
          onClick={() => onChange({ ...filters, onlyAvailable: !filters.onlyAvailable })}
        >
          Solo productos disponibles
        </Check>
      </Section>
    </div>
  )
}
