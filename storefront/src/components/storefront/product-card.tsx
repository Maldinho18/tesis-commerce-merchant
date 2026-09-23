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

/**
 * Escala tipográfica de la tienda, usada sin excepciones:
 *   título de tarjeta   text-sm  font-medium   foreground
 *   precio              text-base font-semibold foreground
 *   metadatos           text-xs                muted-foreground
 * Nada se trunca: los nombres de modelo caben enteros y un nombre cortado con puntos
 * suspensivos es peor que una línea más.
 */
function Tag({ tone, children }: { tone: "accent" | "dark" | "plain"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "rounded-full px-2 py-0.5 text-xs font-medium",
        tone === "accent" && "bg-accent text-accent-foreground",
        tone === "dark" && "bg-foreground text-background",
        tone === "plain" && "bg-background/90 text-muted-foreground backdrop-blur-sm"
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
  const refurbished = conditionsOf(product).includes("refurbished")
  const scarce = product.variants.some((variant) => variant.availability.status === "limited_stock")
  const count = product.variants.length

  return (
    <article
      onClick={() => onOpen(product)}
      className="group flex cursor-pointer flex-col"
    >
      <div className="relative aspect-square overflow-hidden rounded-2xl bg-muted">
        <ProductImage
          src={thumbnail(product.media[0]?.url, 320)}
          alt={product.media[0]?.alt_text ?? product.title}
          seed={product.id}
          category={categoriesOf(product)[0]}
          brand={brandOf(product)}
          className="h-full w-full p-8 transition-transform duration-300 group-hover:scale-105"
        />
        <div className="absolute top-3 left-3 flex flex-wrap gap-1.5">
          {!available && <Tag tone="plain">Agotado</Tag>}
          {available && scarce && <Tag tone="accent">Última unidad</Tag>}
          {refurbished && <Tag tone="dark">{CONDITION_LABELS.refurbished}</Tag>}
        </div>
      </div>

      <div className="flex flex-col gap-1 pt-4">
        <p className="text-xs text-muted-foreground">{brandOf(product)}</p>
        <h3 className="text-sm font-medium text-foreground">{product.title}</h3>
        <p className="pt-1 text-base font-semibold text-foreground tabular-nums">
          {range.min === range.max
            ? formatMoney(range.min, range.currency)
            : `Desde ${formatMoney(range.min, range.currency)}`}
        </p>
        {count > 1 && (
          <p className="text-xs text-muted-foreground">{count} capacidades</p>
        )}
      </div>
    </article>
  )
}
