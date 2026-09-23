import { useState } from "react"
import { Headphones, Keyboard, Laptop, Monitor, Package, Smartphone } from "lucide-react"
import { cn } from "cn"

/** Tono estable por producto: dos productos distintos no comparten respaldo. */
function hue(seed: string): number {
  let hash = 0
  for (const char of seed) hash = (hash * 31 + char.charCodeAt(0)) >>> 0
  return hash % 360
}

const CATEGORY_ICONS = {
  laptops: Laptop,
  headphones: Headphones,
  monitors: Monitor,
  keyboards: Keyboard,
  smartphones: Smartphone,
} as const

type Props = {
  src: string | undefined
  alt: string
  seed: string
  category?: string
  brand?: string
  className?: string
}

/**
 * El feed publica URLs de imagen del comercio. Mientras un producto no tenga foto, el respaldo
 * muestra el tipo de producto y la marca, de modo que la retícula se lee como una tienda y no
 * como una imagen rota.
 */
export function ProductImage({ src, alt, seed, category, brand, className }: Props) {
  const [failed, setFailed] = useState(false)

  if (!src || failed) {
    // El respaldo no compite con las fotos reales: fondo casi blanco y un tinte mínimo
    // derivado del producto, solo para que dos tarjetas contiguas no se confundan.
    const tone = hue(seed)
    const Icon = CATEGORY_ICONS[category as keyof typeof CATEGORY_ICONS] ?? Package
    return (
      <div
        role="img"
        aria-label={alt}
        className={cn("flex flex-col items-center justify-center gap-2", className)}
        style={{ background: `oklch(0.985 0.006 ${tone})`, color: `oklch(0.62 0.02 ${tone})` }}
      >
        <Icon className="size-10" strokeWidth={1.25} />
        {brand && (
          <span className="text-[0.7rem] font-medium tracking-wide uppercase">{brand}</span>
        )}
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      onError={() => setFailed(true)}
      className={cn("object-contain", className)}
    />
  )
}
