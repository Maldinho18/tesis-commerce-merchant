import {
  brandOf,
  categoriesOf,
  conditionsOf,
  inStock,
  priceRange,
  type FeedProduct,
} from "@/lib/catalog"

export type Filters = {
  category: string | null
  brand: string | null
  condition: string | null
  maxAmount: number | null
  onlyAvailable: boolean
}

export const EMPTY_FILTERS: Filters = {
  category: null,
  brand: null,
  condition: null,
  maxAmount: null,
  onlyAvailable: false,
}

export function activeFilterCount(filters: Filters): number {
  return (
    Number(filters.category !== null) +
    Number(filters.brand !== null) +
    Number(filters.condition !== null) +
    Number(filters.maxAmount !== null) +
    Number(filters.onlyAvailable)
  )
}

/** Mismo predicado que aplica el comprador sobre sus restricciones duras. */
export function matchesFilters(product: FeedProduct, filters: Filters): boolean {
  if (filters.category && !categoriesOf(product).includes(filters.category)) return false
  if (filters.brand && brandOf(product) !== filters.brand) return false
  if (filters.condition && !conditionsOf(product).includes(filters.condition)) return false
  if (filters.onlyAvailable && !inStock(product)) return false
  if (filters.maxAmount !== null && priceRange(product).min > filters.maxAmount) return false
  return true
}

/** Topes redondos derivados del catálogo real, para que los chips no sean arbitrarios. */
export function budgetSteps(products: FeedProduct[]): number[] {
  if (products.length === 0) return []
  const max = Math.max(...products.map((product) => priceRange(product).max))
  const million = 1_000_000_00
  return [million, 3 * million, 6 * million, 12 * million].filter((amount) => amount < max)
}
