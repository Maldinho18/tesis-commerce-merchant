import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { ProductImage } from "@/components/storefront/product-image"
import {
  AVAILABILITY_LABELS,
  CATEGORY_LABELS,
  CONDITION_LABELS,
  brandOf,
  categoriesOf,
  conditionsOf,
  formatMoney,
  inStock,
  priceRange,
  type FeedProduct,
} from "@/lib/catalog"

/** Dimensiones por las que varía un producto, para anunciar "4 configuraciones · RAM, GPU". */
function varyingOptions(product: FeedProduct): string[] {
  if (product.variants.length < 2) return []
  const seen = new Map<string, Set<string>>()
  for (const variant of product.variants) {
    for (const option of variant.variant_options) {
      const values = seen.get(option.name) ?? new Set<string>()
      values.add(option.value)
      seen.set(option.name, values)
    }
  }
  return [...seen.entries()].filter(([, values]) => values.size > 1).map(([name]) => name)
}

export function ProductCard({
  product,
  onOpen,
}: {
  product: FeedProduct
  onOpen: (product: FeedProduct) => void
}) {
  const range = priceRange(product)
  const available = inStock(product)
  const categories = categoriesOf(product)
  const conditions = conditionsOf(product)
  const varying = varyingOptions(product)
  const scarce = product.variants.some(
    (variant) => variant.availability.status === "limited_stock"
  )

  return (
    <Card
      onClick={() => onOpen(product)}
      className="group cursor-pointer gap-0 overflow-hidden p-0 transition-shadow hover:shadow-md"
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-secondary/40">
        <ProductImage
          src={product.media[0]?.url}
          alt={product.media[0]?.alt_text ?? product.title}
          seed={product.id}
          category={categories[0]}
          brand={brandOf(product)}
          className="h-full w-full p-6 transition-transform group-hover:scale-[1.03]"
        />
        <div className="absolute top-2 left-2 flex flex-wrap gap-1">
          {!available && <Badge variant="outline">{AVAILABILITY_LABELS.out_of_stock}</Badge>}
          {available && scarce && <Badge variant="accent">Última unidad</Badge>}
          {conditions.includes("refurbished") && (
            <Badge variant="muted">{CONDITION_LABELS.refurbished}</Badge>
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <div className="flex flex-wrap gap-1">
          {categories.map((category) => (
            <span key={category} className="text-xs text-muted-foreground">
              {CATEGORY_LABELS[category] ?? category}
            </span>
          ))}
        </div>
        <h3 className="text-sm leading-snug font-medium">{product.title}</h3>
        <p className="line-clamp-2 text-xs text-muted-foreground">{product.description.plain}</p>

        <div className="mt-auto pt-3">
          <p className="text-base font-semibold tabular-nums">
            {range.min === range.max
              ? formatMoney(range.min, range.currency)
              : `Desde ${formatMoney(range.min, range.currency)}`}
          </p>
          {product.variants.length > 1 && (
            <p className="text-xs text-muted-foreground">
              {product.variants.length} configuraciones
              {varying.length > 0 && ` · ${varying.join(" · ")}`}
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}
