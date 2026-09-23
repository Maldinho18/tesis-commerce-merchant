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
    const tone = hue(seed)
    const Icon = CATEGORY_ICONS[category as keyof typeof CATEGORY_ICONS] ?? Package
    return (
      <div
        role="img"
        aria-label={alt}
        className={cn("flex flex-col items-center justify-center gap-2", className)}
        style={{
          background: `linear-gradient(140deg, oklch(0.96 0.02 ${tone}), oklch(0.91 0.04 ${tone}))`,
          color: `oklch(0.45 0.07 ${tone})`,
        }}
      >
        <Icon className="size-8 opacity-70" strokeWidth={1.5} />
        {brand && <span className="text-xs font-medium tracking-wide">{brand}</span>}
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
