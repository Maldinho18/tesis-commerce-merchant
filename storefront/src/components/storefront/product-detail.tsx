import { useEffect, useState } from "react"
import { Check, Package, Truck, X } from "lucide-react"

import { ProductImage } from "@/components/storefront/product-image"
import {
  AVAILABILITY_LABELS,
  CATEGORY_LABELS,
  CONDITION_LABELS,
  brandOf,
  categoriesOf,
  formatMoney,
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
      <dt className="w-28 shrink-0 text-gray-600">{label}</dt>
      <dd className="min-w-0 font-medium">{children}</dd>
    </div>
  )
}

function availabilityTone(status: string) {
  if (status === "out_of_stock") return "text-gray-500"
  if (status === "limited_stock") return "text-accent"
  return "text-primary"
}

export function ProductDetail({
  product,
  onClose,
}: {
  product: FeedProduct
  onClose: () => void
}) {
  const [selectedId, setSelectedId] = useState(product.variants[0]?.id ?? "")
  const [tab, setTab] = useState<Tab>("descripcion")

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const selected: FeedVariant | undefined =
    product.variants.find((variant) => variant.id === selectedId) ?? product.variants[0]
  if (!selected) return null

  const brand = brandOf(product)
  const category = categoriesOf(product)[0]

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-gray-900/50 p-0 sm:p-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={product.title}
        onClick={(event) => event.stopPropagation()}
        className="relative w-full max-w-5xl bg-background shadow-xl"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Cerrar"
          className="absolute top-3 right-3 z-10 grid size-8 place-items-center bg-gray-50 text-gray-600 hover:bg-gray-900 hover:text-primary-foreground"
        >
          <X className="size-4" />
        </button>

        <div className="grid gap-8 p-5 sm:p-8 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
          <div>
            <div className="aspect-square overflow-hidden border border-border bg-gray-50">
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
            <p className="text-xs font-semibold tracking-wide text-gray-500 uppercase">{brand}</p>
            <h2 className="mt-1 text-xl leading-snug font-semibold">{product.title}</h2>

            <p
              className={cn(
                "mt-2 text-sm font-medium",
                availabilityTone(selected.availability.status)
              )}
            >
              {AVAILABILITY_LABELS[selected.availability.status] ?? selected.availability.status}
            </p>

            <div className="mt-4 border-y border-border py-4">
              <p className="text-3xl font-bold text-primary tabular-nums">
                {formatMoney(selected.price.amount, selected.price.currency)}
              </p>
              <p className="mt-1 text-xs text-gray-600">
                Precio del artículo. El envío se calcula en el checkout.
              </p>
            </div>

            {product.variants.length > 1 && (
              <div className="mt-4">
                <p className="mb-2 text-xs font-semibold tracking-wide uppercase">
                  {product.variants.length} configuraciones
                </p>
                <div className="flex flex-wrap gap-2">
                  {product.variants.map((variant) => {
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
                            ? "border-primary bg-primary/5 font-medium text-primary"
                            : "border-border text-gray-600 hover:border-gray-400",
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
                    ? "border-primary font-semibold text-foreground"
                    : "border-transparent text-gray-600 hover:text-foreground"
                )}
              >
                {TAB_LABELS[key]}
              </button>
            ))}
          </div>
        </div>

        <div className="px-5 py-6 sm:px-8">
          {tab === "descripcion" && (
            <p className="max-w-3xl text-sm leading-relaxed text-gray-600">
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
                  <dt className="text-gray-600">{option.name}</dt>
                  <dd className="text-right font-medium">{option.value}</dd>
                </div>
              ))}
            </dl>
          )}

          {tab === "entrega" && (
            <div className="max-w-3xl space-y-3 text-sm text-gray-600">
              <p className="flex items-start gap-2">
                <Truck className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                Entrega sintética a Bogotá. El costo y la fecha los fija el comercio al crear el
                checkout, no este catálogo.
              </p>
              <p className="flex items-start gap-2">
                <Package className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
                Esta vitrina es de solo consulta. La compra ocurre por el canal ACP, que atiende al
                agente comprador con su propia credencial; el precio de aquí es una observación y
                el comercio revalida los términos antes de cobrar.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
