/** Proyección pública del catálogo del comercio: la misma que consume el comprador por ACP. */

export type FeedPrice = { amount: number; currency: string }
export type FeedAvailability = { available: boolean; status: string }
export type FeedOption = { name: string; value: string }

export type FeedVariant = {
  id: string
  title: string
  url: string
  price: FeedPrice
  availability: FeedAvailability
  categories: Array<{ value: string; taxonomy: string }>
  condition: string[]
  variant_options: FeedOption[]
}

export type FeedProduct = {
  id: string
  title: string
  description: { plain: string }
  url: string
  media: Array<{ type: string; url: string; alt_text?: string }>
  variants: FeedVariant[]
}

export type Catalog = {
  metadata: { id: string; target_country: string; updated_at: string }
  products: FeedProduct[]
}

const RAW_BASE = import.meta.env.VITE_MERCHANT_API_URL ?? "http://127.0.0.1:4120"
export const MERCHANT_ORIGIN = RAW_BASE.replace(/\/+$/, "")

export async function fetchCatalog(signal?: AbortSignal): Promise<Catalog> {
  const response = await fetch(`${MERCHANT_ORIGIN}/storefront/catalog`, { signal })
  if (!response.ok) throw new Error(`El comercio respondió ${response.status}`)
  return (await response.json()) as Catalog
}

const LOCALE = "es-CO"

/**
 * Los montos llegan en unidades menores. COP tiene exponente dos, así que dividir por cien
 * es obligatorio: omitirlo multiplica cada precio por cien y sigue pareciendo un precio real.
 */
export function formatMoney(amountMinor: number, currency: string): string {
  const amount = amountMinor / 100
  try {
    return new Intl.NumberFormat(LOCALE, {
      style: "currency",
      currency: currency.toUpperCase(),
      currencyDisplay: "narrowSymbol",
      maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    return amount.toLocaleString(LOCALE)
  }
}

export function categoriesOf(product: FeedProduct): string[] {
  const values = new Set<string>()
  for (const variant of product.variants) {
    for (const row of variant.categories) values.add(row.value)
  }
  return [...values]
}

export function conditionsOf(product: FeedProduct): string[] {
  const values = new Set<string>()
  for (const variant of product.variants) {
    for (const value of variant.condition) values.add(value)
  }
  return [...values]
}

/** Marca declarada por el vendedor; el feed no la expone aparte, así que sale del título. */
export function brandOf(product: FeedProduct): string {
  return product.title.split(" ")[0] ?? ""
}

export function priceRange(product: FeedProduct): { min: number; max: number; currency: string } {
  const amounts = product.variants.map((variant) => variant.price.amount)
  return {
    min: Math.min(...amounts),
    max: Math.max(...amounts),
    currency: product.variants[0]?.price.currency ?? "COP",
  }
}

export function inStock(product: FeedProduct): boolean {
  return product.variants.some((variant) => variant.availability.available)
}

export const CATEGORY_LABELS: Record<string, string> = {
  laptops: "Portátiles",
  headphones: "Audífonos",
  monitors: "Monitores",
  keyboards: "Teclados",
  smartphones: "Celulares",
}

export const AVAILABILITY_LABELS: Record<string, string> = {
  in_stock: "Disponible",
  limited_stock: "Última unidad",
  out_of_stock: "Agotado",
}

export const CONDITION_LABELS: Record<string, string> = {
  new: "Nuevo",
  refurbished: "Reacondicionado",
}
