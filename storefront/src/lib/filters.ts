import {
  brandOf,
  categoriesOf,
  conditionsOf,
  inStock,
  priceRange,
  type FeedProduct,
} from "@/lib/catalog"

export type Filters = {
  query: string
  category: string | null
  brand: string | null
  condition: string | null
  maxAmount: number | null
  onlyAvailable: boolean
}

export const EMPTY_FILTERS: Filters = {
  query: "",
  category: null,
  brand: null,
  condition: null,
  maxAmount: null,
  onlyAvailable: false,
}

export function activeFilterCount(filters: Filters): number {
  return (
    Number(filters.query.trim().length > 0) +
    Number(filters.category !== null) +
    Number(filters.brand !== null) +
    Number(filters.condition !== null) +
    Number(filters.maxAmount !== null) +
    Number(filters.onlyAvailable)
  )
}

/** Texto sobre el que busca la vitrina: título, descripción y valores de opción. */
function searchText(product: FeedProduct): string {
  const parts = [product.title, product.description.plain]
  for (const variant of product.variants) {
    parts.push(variant.title)
    for (const option of variant.variant_options) parts.push(option.value)
  }
  return parts.join(" ").toLowerCase()
}

/** Mismo predicado que aplica el comprador sobre sus restricciones duras, más el buscador. */
export function matchesFilters(product: FeedProduct, filters: Filters): boolean {
  const query = filters.query.trim().toLowerCase()
  if (query) {
    const haystack = searchText(product)
    // Todos los términos deben aparecer: "samsung 512" acota, no ensancha.
    if (!query.split(/\s+/).every((term) => haystack.includes(term))) return false
  }
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

/** Productos por página en la retícula. */
export const PAGE_SIZE = 48

export type SortKey = "relevance" | "price-asc" | "price-desc" | "name"

export const SORT_LABELS: Record<SortKey, string> = {
  relevance: "Relevancia",
  "price-asc": "Precio: menor a mayor",
  "price-desc": "Precio: mayor a menor",
  name: "Nombre A-Z",
}

/** Orden estable: el desempate por id evita que dos productos del mismo precio bailen. */
export function sortProducts(products: FeedProduct[], key: SortKey): FeedProduct[] {
  if (key === "relevance") return products
  const sorted = [...products]
  sorted.sort((left, right) => {
    if (key === "name") return left.title.localeCompare(right.title, "es")
    const a = priceRange(left).min
    const b = priceRange(right).min
    const delta = key === "price-asc" ? a - b : b - a
    return delta || left.id.localeCompare(right.id)
  })
  return sorted
}
