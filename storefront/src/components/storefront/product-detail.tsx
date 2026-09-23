import { useEffect } from "react"
import { X } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ProductImage } from "@/components/storefront/product-image"
import {
  AVAILABILITY_LABELS,
  CATEGORY_LABELS,
  CONDITION_LABELS,
  brandOf,
  categoriesOf,
  formatMoney,
  type FeedProduct,
  type FeedVariant,
} from "@/lib/catalog"

function availabilityVariant(status: string) {
  if (status === "out_of_stock") return "outline" as const
  if (status === "limited_stock") return "accent" as const
  return "secondary" as const
}

function VariantRow({ variant }: { variant: FeedVariant }) {
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-mono text-xs text-muted-foreground">{variant.id}</span>
          <Badge variant={availabilityVariant(variant.availability.status)}>
            {AVAILABILITY_LABELS[variant.availability.status] ?? variant.availability.status}
          </Badge>
          {variant.condition
            .filter((condition) => condition !== "new")
            .map((condition) => (
              <Badge key={condition} variant="muted">
                {CONDITION_LABELS[condition] ?? condition}
              </Badge>
            ))}
        </div>
        <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
          {variant.variant_options.map((option) => (
            <div key={option.name} className="flex gap-1 text-xs">
              <dt className="text-muted-foreground">{option.name}:</dt>
              <dd className="font-medium">{option.value}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="shrink-0 text-sm font-semibold tabular-nums sm:text-right">
        {formatMoney(variant.price.amount, variant.price.currency)}
      </p>
    </li>
  )
}

export function ProductDetail({
  product,
  onClose,
}: {
  product: FeedProduct
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-foreground/30 p-4 sm:p-8">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={product.title}
        className="relative w-full max-w-3xl rounded-xl bg-card ring-1 ring-foreground/10"
      >
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onClose}
          aria-label="Cerrar"
          className="absolute top-3 right-3 z-10"
        >
          <X />
        </Button>

        <div className="grid gap-6 p-5 sm:grid-cols-[minmax(0,14rem)_minmax(0,1fr)] sm:p-6">
          <div className="aspect-square shrink-0 overflow-hidden rounded-lg bg-secondary/40">
            <ProductImage
              src={product.media[0]?.url}
              alt={product.media[0]?.alt_text ?? product.title}
              seed={product.id}
              category={categoriesOf(product)[0]}
              brand={brandOf(product)}
              className="h-full w-full p-5"
            />
          </div>

          <div className="min-w-0">
            <div className="flex flex-wrap gap-1.5">
              {categoriesOf(product).map((category) => (
                <Badge key={category} variant="muted">
                  {CATEGORY_LABELS[category] ?? category}
                </Badge>
              ))}
            </div>
            <h2 className="mt-2 text-lg font-semibold tracking-tight">{product.title}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{product.description.plain}</p>

            <h3 className="mt-5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
              {product.variants.length === 1
                ? "Configuración"
                : `${product.variants.length} configuraciones`}
            </h3>
            <ul className="divide-y divide-border">
              {product.variants.map((variant) => (
                <VariantRow key={variant.id} variant={variant} />
              ))}
            </ul>

            <p className="mt-5 rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
              Esta vitrina es solo de consulta. La compra ocurre por el canal ACP, que atiende al
              agente comprador con su propia credencial.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
