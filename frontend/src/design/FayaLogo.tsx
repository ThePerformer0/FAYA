/**
 * Identité visuelle Faya (alignée 1:1 sur /favicon.png).
 * - Variante couleur : utilise directement le visuel officiel /favicon.png.
 * - Variantes monochromes / état vide : silhouette vectorielle fidèle à la favicon.
 * - Mot-symbole FAYA : lettrage géométrique sur mesure, distinct de la typographie courante.
 */

interface FayaMarkProps {
  variant?: "color" | "ink" | "paper" | "muted";
  size?: number;
  className?: string;
}

export function FayaMark({ variant = "color", size = 30, className = "" }: FayaMarkProps) {
  if (variant === "color") {
    return (
      <img
        src="/favicon.png"
        alt=""
        width={size}
        height={size}
        aria-hidden="true"
        className={`shrink-0 rounded-[7px] object-contain ${className}`}
        style={{ width: size, height: size }}
      />
    );
  }

  const tileFill =
    variant === "ink"
      ? "#1C1814"
      : variant === "paper"
        ? "#FDFDFF"
        : "#D9D2CB";

  const flameFill = variant === "paper" ? "#1C1814" : "#FDFDFF";

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      className={`shrink-0 ${className}`}
    >
      <rect width="64" height="64" rx="14" fill={tileFill} />
      {/* Flamme à trois pointes fidèle à la favicon */}
      <path
        d="M28.5 8.5C35.5 13.5 41 20.5 40.5 28.5C42.8 26.2 44.3 23.6 44.8 20.8C49.5 25.4 52 31.4 52 38C52 48.2 43.2 55.5 32 55.5C20.8 55.5 12 48.2 12 38C12 31.2 15.2 25.1 20.5 20.6C19.9 23.8 20.5 26.7 22.3 29.2C22.4 20.2 28.5 15.3 28.5 8.5Z"
        fill={flameFill}
      />
      {/* Bouteille de gaz en négatif */}
      <rect x="26.5" y="23.5" width="11" height="3.2" rx="1.6" fill={tileFill} />
      <rect x="28.2" y="26.3" width="2.2" height="3.4" fill={tileFill} />
      <rect x="33.6" y="26.3" width="2.2" height="3.4" fill={tileFill} />
      <rect x="24.5" y="29" width="15" height="17.5" rx="4.5" fill={tileFill} />
      <rect x="24" y="37.2" width="16" height="1.5" rx="0.75" fill={flameFill} />
      <path d="M26.8 47.4H37.2L36.2 50.2H27.8L26.8 47.4Z" fill={tileFill} />
    </svg>
  );
}

/**
 * Mot-symbole vectoriel FAYA : géométrie industrielle angulaire avec accent rouge Faya,
 * visuellement distinct de la police Barlow utilisée dans l'interface.
 */
export function FayaWordmark({
  variant = "color",
  size = 30,
  onDark = false,
}: {
  variant?: "color" | "ink" | "paper";
  size?: number;
  onDark?: boolean;
}) {
  const ink = onDark || variant === "paper" ? "#FDFDFF" : "#181411";
  const accent = variant === "ink" ? "#181411" : "#F42902";

  return (
    <span className="inline-flex items-center gap-2.5">
      <FayaMark variant={variant} size={size} />
      <svg
        width="82"
        height="26"
        viewBox="0 0 116 36"
        fill="none"
        role="img"
        aria-label="Faya"
        className="shrink-0"
      >
        {/* F : coupe supérieure inclinée */}
        <path
          d="M3 4H25L22.5 10.5H10.5V15.5H21.2L19 21.5H10.5V31H3V4Z"
          fill={ink}
        />
        {/* A : apex tronqué et barre transversale rouge Faya */}
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M35.5 4H44.5L54 31H46L44 24.5H34.5L32.5 31H24.8L35.5 4ZM36.2 18.8H42.3L39.4 9.8H39.1L36.2 18.8Z"
          fill={ink}
        />
        <path d="M35.2 21.2H43.3L42.5 24.5H34.4L35.2 21.2Z" fill={accent} />
        {/* Y : fourche tendue */}
        <path
          d="M52.5 4H61L66.8 15.8H67.1L73 4H81.2L70.8 21.8V31H63.2V21.8L52.5 4Z"
          fill={ink}
        />
        {/* A : second A symétrique */}
        <path
          fillRule="evenodd"
          clipRule="evenodd"
          d="M89.5 4H98.5L108 31H100L98 24.5H88.5L86.5 31H78.8L89.5 4ZM90.2 18.8H96.3L93.4 9.8H93.1L90.2 18.8Z"
          fill={ink}
        />
        {/* Point carré signature Faya */}
        <rect x="109.5" y="24.5" width="6.5" height="6.5" rx="1.2" fill={accent} />
      </svg>
    </span>
  );
}
