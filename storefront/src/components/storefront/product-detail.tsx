import { useState } from "react"
import { ArrowLeft, Check, Package, Truck } from "lucide-react"

import { ProductImage } from "@/components/storefront/product-image"
import {
  AVAILABILITY_LABELS,
  CATEGORY_LABELS,
  CONDITION_LABELS,
  brandOf,
  categoriesOf,
  formatMoney,
  orderedVariants,
  thumbnail,
  type FeedProduct,
  type FeedVariant,
} from "@/lib/catalog"
import { cn } from "cn"

type Tab = "descripcion" | "especificaciones" | "entrega"

const TAB_LABELS: Record<Tab, string> = {
  descripcion: "Descripción",
  especificaciones: "Especificaciones",
  entrega: "Entrega y compra",
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2 text-sm">
      <dt className="w-28 shrink-0 text-muted-foreground">{label}</dt>
      <dd className="min-w-0 font-medium">{children}</dd>
    </div>
  )
}

function availabilityTone(status: string) {
  if (status === "out_of_stock") return "text-muted-foreground"
  if (status === "limited_stock") return "text-accent"
  return "text-foreground"
}

export function ProductDetail({
  product,
  onBack,
}: {
  product: FeedProduct
  onBack: () => void
}) {
  const variants = orderedVariants(product)
  const [selectedId, setSelectedId] = useState(variants[0]?.id ?? "")
  const [tab, setTab] = useState<Tab>("descripcion")

  const selected: FeedVariant | undefined =
    variants.find((variant) => variant.id === selectedId) ?? variants[0]
  if (!selected) return null

  const brand = brandOf(product)
  const category = categoriesOf(product)[0] ?? ""

  return (
    <div className="mx-auto w-full max-w-7xl px-4 pt-4 pb-10 sm:px-6">
      <nav className="text-xs text-muted-foreground" aria-label="Ruta">
        <ol className="flex flex-wrap items-center gap-1.5">
          <li>
            <button type="button" onClick={onBack} className="hover:text-primary">
              Inicio
            </button>
          </li>
          <li aria-hidden>›</li>
          <li>{CATEGORY_LABELS[category] ?? category}</li>
          <li aria-hidden>›</li>
          <li className="font-medium text-foreground">{product.title}</li>
        </ol>
      </nav>

      <button
        type="button"
        onClick={onBack}
        className="mt-3 inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Volver al catálogo
      </button>

      <div className="mt-4 border border-border bg-background">
        <div className="grid gap-8 p-5 sm:p-8 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <div>
            <div className="aspect-square overflow-hidden border border-border bg-muted">
              <ProductImage
                src={thumbnail(product.media[0]?.url, 480)}
                alt={product.media[0]?.alt_text ?? product.title}
                seed={product.id}
                category={category}
                brand={brand}
                className="h-full w-full p-8"
              />
            </div>
          </div>

          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{brand}</p>
            <h2 className="mt-1 text-xl leading-snug font-semibold">{product.title}</h2>

            <p
              className={cn(
                "mt-2 text-sm",
                availabilityTone(selected.availability.status)
              )}
            >
              {AVAILABILITY_LABELS[selected.availability.status] ?? selected.availability.status}
            </p>

            <div className="mt-4 border-y border-border py-4">
              <p className="text-3xl font-semibold text-foreground tabular-nums">
                {formatMoney(selected.price.amount, selected.price.currency)}
              </p>
              <p className="mt-1.5 text-xs text-muted-foreground">Envío calculado en el checkout.</p>
            </div>

            {product.variants.length > 1 && (
              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold tracking-wide uppercase">
                  {product.variants.length} configuraciones
                </p>
                <div className="flex flex-wrap gap-2">
                  {variants.map((variant) => {
                    const active = variant.id === selected.id
                    const label =
                      variant.variant_options
                        .filter((option) => option.name !== "Color")
                        .map((option) => option.value)
                        .join(" · ") || variant.title
                    return (
                      <button
                        key={variant.id}
                        type="button"
                        onClick={() => setSelectedId(variant.id)}
                        aria-pressed={active}
                        className={cn(
                          "flex items-center gap-1.5 border px-3 py-1.5 text-xs transition-colors",
                          active
                            ? "border-foreground bg-foreground text-background"
                            : "border-border text-muted-foreground hover:border-foreground/30",
                          !variant.availability.available && "opacity-50"
                        )}
                      >
                        {active && <Check className="size-3" aria-hidden />}
                        {label}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            <dl className="mt-5 space-y-1.5">
              <Row label="SKU">
                <span className="font-mono text-xs">{selected.id}</span>
              </Row>
              <Row label="Marca">{brand}</Row>
              <Row label="Categoría">{CATEGORY_LABELS[category] ?? category}</Row>
              <Row label="Condición">
                {selected.condition
                  .map((value) => CONDITION_LABELS[value] ?? value)
                  .join(", ")}
              </Row>
            </dl>
          </div>
        </div>

        <div className="border-t border-border px-5 sm:px-8">
          <div className="flex gap-6">
            {(Object.keys(TAB_LABELS) as Tab[]).map((key) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                aria-current={tab === key ? "true" : undefined}
                className={cn(
                  "-mb-px border-b-2 py-3 text-sm transition-colors",
                  tab === key
                    ? "border-foreground font-medium text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {TAB_LABELS[key]}
              </button>
            ))}
          </div>
        </div>

        <div className="px-5 py-6 sm:px-8">
          {tab === "descripcion" && (
            <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
              {product.description.plain}
            </p>
          )}

          {tab === "especificaciones" && (
            <dl className="grid max-w-3xl gap-x-8 gap-y-2 sm:grid-cols-2">
              {selected.variant_options.map((option) => (
                <div
                  key={option.name}
                  className="flex justify-between gap-4 border-b border-border py-2 text-sm"
                >
                  <dt className="text-muted-foreground">{option.name}</dt>
                  <dd className="text-right font-medium">{option.value}</dd>
                </div>
              ))}
            </dl>
          )}

          {tab === "entrega" && (
            <div className="max-w-3xl space-y-3 text-sm text-muted-foreground">
              <p className="flex items-start gap-2.5">
                <Truck className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                Entrega a Bogotá. El comercio fija el costo y la fecha al crear el checkout.
              </p>
              <p className="flex items-start gap-2.5">
                <Package className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden />
                Vitrina de consulta. La compra ocurre por el canal ACP y el comercio revalida los
                términos antes de cobrar.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
