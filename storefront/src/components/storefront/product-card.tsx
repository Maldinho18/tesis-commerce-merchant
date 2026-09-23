import { ArrowUpRight } from "lucide-react"

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
import { cn } from "cn"

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

function Tag({ tone, children }: { tone: "accent" | "muted" | "off"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-[0.65rem] font-medium",
        tone === "accent" && "bg-accent text-accent-foreground",
        tone === "muted" && "bg-foreground/85 text-background",
        tone === "off" && "bg-background/90 text-gray-600 backdrop-blur-sm"
      )}
    >
      {children}
    </span>
  )
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
      className="group flex cursor-pointer flex-col rounded-xl bg-card transition-all duration-200 hover:-translate-y-0.5 hover:shadow-[0_8px_24px_-8px_rgb(0_0_0/0.12)]"
    >
      <div className="relative aspect-square overflow-hidden rounded-xl bg-muted">
        <ProductImage
          src={thumbnail(product.media[0]?.url, 320)}
          alt={product.media[0]?.alt_text ?? product.title}
          seed={product.id}
          category={categoriesOf(product)[0]}
          brand={brandOf(product)}
          className="h-full w-full p-7 transition-transform duration-300 group-hover:scale-[1.04]"
        />
        <div className="absolute top-2 left-2 flex flex-col items-start gap-1">
          {!available && <Tag tone="off">Agotado</Tag>}
          {available && scarce && <Tag tone="accent">Última unidad</Tag>}
          {conditions.includes("refurbished") && (
            <Tag tone="muted">{CONDITION_LABELS.refurbished}</Tag>
          )}
        </div>
        <span
          className="absolute right-3 bottom-3 grid size-9 place-items-center rounded-full bg-background/90 text-foreground opacity-0 shadow-sm backdrop-blur-sm transition-opacity group-hover:opacity-100"
          aria-hidden
        >
          <ArrowUpRight className="size-4" />
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-1 px-1 pt-3 pb-1">
        <p className="text-xs text-gray-500">{brandOf(product)}</p>
        <h3 className="line-clamp-2 text-[0.9rem] leading-snug font-medium text-foreground">
          {product.title}
        </h3>

        <div className="mt-auto pt-2">
          <p className="text-[1.05rem] leading-tight font-semibold text-foreground tabular-nums">
            {range.min !== range.max && (
              <span className="mr-1 text-xs font-normal text-gray-500">Desde</span>
            )}
            {formatMoney(range.min, range.currency)}
          </p>
          <p className="mt-0.5 line-clamp-1 text-xs text-gray-500">
            {product.variants.length > 1
              ? `${product.variants.length} opciones${varying.length > 0 ? ` · ${varying.join(" · ")}` : ""}`
              : "Única presentación"}
          </p>
        </div>
      </div>
    </article>
  )
}
