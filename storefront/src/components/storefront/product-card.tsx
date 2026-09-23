import { Badge } from "@/components/ui/badge"
import { ProductImage } from "@/components/storefront/product-image"
import {
  CONDITION_LABELS,
  brandOf,
  categoriesOf,
  conditionsOf,
  formatMoney,
  inStock,
  priceRange,
  thumbnail,
  type FeedProduct,
} from "@/lib/catalog"

/** Dimensiones por las que varía un producto, para anunciar "4 opciones · RAM, GPU". */
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
  const conditions = conditionsOf(product)
  const varying = varyingOptions(product)
  const scarce = product.variants.some((variant) => variant.availability.status === "limited_stock")

  return (
    <article
      onClick={() => onOpen(product)}
      className="group flex cursor-pointer flex-col rounded-xl border border-border bg-card transition-shadow hover:shadow-lg"
    >
      <div className="relative aspect-square overflow-hidden rounded-t-xl bg-white">
        <ProductImage
          src={thumbnail(product.media[0]?.url, 320)}
          alt={product.media[0]?.alt_text ?? product.title}
          seed={product.id}
          category={categoriesOf(product)[0]}
          brand={brandOf(product)}
          className="h-full w-full p-5 transition-transform duration-300 group-hover:scale-105"
        />
        <div className="absolute top-2 left-2 flex flex-col items-start gap-1">
          {!available && <Badge variant="outline">Agotado</Badge>}
          {available && scarce && <Badge variant="accent">Última unidad</Badge>}
          {conditions.includes("refurbished") && (
            <Badge variant="muted">{CONDITION_LABELS.refurbished}</Badge>
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-1 border-t border-border p-3">
        <p className="text-[0.7rem] font-medium tracking-wide text-muted-foreground uppercase">
          {brandOf(product)}
        </p>
        <h3 className="line-clamp-2 text-sm leading-snug font-medium">{product.title}</h3>

        <div className="mt-auto pt-2">
          {range.min !== range.max && (
            <p className="text-[0.7rem] text-muted-foreground">Desde</p>
          )}
          <p className="text-lg leading-tight font-semibold tabular-nums">
            {formatMoney(range.min, range.currency)}
          </p>
          <p className="mt-0.5 line-clamp-1 text-[0.7rem] text-muted-foreground">
            {product.variants.length > 1
              ? `${product.variants.length} opciones${varying.length > 0 ? ` · ${varying.join(" · ")}` : ""}`
              : "Única presentación"}
          </p>
        </div>
      </div>
    </article>
  )
}
