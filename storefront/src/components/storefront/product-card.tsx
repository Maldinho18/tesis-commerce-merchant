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
        "rounded-sm px-1.5 py-0.5 text-[0.65rem] font-semibold tracking-wide uppercase",
        tone === "accent" && "bg-accent text-accent-foreground",
        tone === "muted" && "bg-gray-900 text-primary-foreground",
        tone === "off" && "bg-background text-gray-600 ring-1 ring-border"
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
      className="group flex cursor-pointer flex-col border border-border bg-card transition-colors hover:border-primary"
    >
      <div className="relative aspect-square overflow-hidden bg-gray-50">
        <ProductImage
          src={thumbnail(product.media[0]?.url, 320)}
          alt={product.media[0]?.alt_text ?? product.title}
          seed={product.id}
          category={categoriesOf(product)[0]}
          brand={brandOf(product)}
          className="h-full w-full p-6 transition-transform duration-300 group-hover:scale-105"
        />
        <div className="absolute top-2 left-2 flex flex-col items-start gap-1">
          {!available && <Tag tone="off">Agotado</Tag>}
          {available && scarce && <Tag tone="accent">Última unidad</Tag>}
          {conditions.includes("refurbished") && (
            <Tag tone="muted">{CONDITION_LABELS.refurbished}</Tag>
          )}
        </div>
        <span
          className="absolute right-2 bottom-2 grid size-8 place-items-center rounded-sm bg-gray-900 text-primary-foreground opacity-0 transition-opacity group-hover:opacity-100"
          aria-hidden
        >
          <ArrowUpRight className="size-4" />
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="text-[0.65rem] font-semibold tracking-wide text-gray-500 uppercase">
          {brandOf(product)}
        </p>
        <h3 className="line-clamp-2 text-sm leading-snug font-medium text-foreground">
          {product.title}
        </h3>

        <div className="mt-auto pt-2">
          <p className="text-lg leading-tight font-bold text-primary tabular-nums">
            {range.min !== range.max && (
              <span className="mr-1 text-[0.7rem] font-medium text-gray-500">Desde</span>
            )}
            {formatMoney(range.min, range.currency)}
          </p>
          <p className="mt-1 line-clamp-1 text-[0.7rem] text-gray-600">
            {product.variants.length > 1
              ? `${product.variants.length} opciones${varying.length > 0 ? ` · ${varying.join(" · ")}` : ""}`
              : "Única presentación"}
          </p>
        </div>
      </div>
    </article>
  )
}
