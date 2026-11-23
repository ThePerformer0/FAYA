/**
 * Symbole bouteille de gaz + flamme Faya (DESIGN_SYSTEM §7.1).
 * Forme pleine, sans dégradé, lisible dès 16 px et en monochrome.
 */

interface FayaMarkProps {
  variant?: "color" | "ink" | "paper" | "muted";
  size?: number;
  className?: string;
}

export function FayaMark({ variant = "color", size = 28, className = "" }: FayaMarkProps) {
  const outerFill =
    variant === "color"
      ? "#F42902"
      : variant === "ink"
        ? "#1C1814"
        : variant === "paper"
          ? "#FDFDFF"
          : "#D9D2CB";

  const bottleCutout =
    variant === "paper" ? "#1C1814" : "#FDFDFF";

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M16 2.5C20.5 7.2 25.5 11.8 25.5 18.4C25.5 24.3 21.2 29.5 16 29.5C10.8 29.5 6.5 24.3 6.5 18.4C6.5 11.8 11.5 7.2 16 2.5Z"
        fill={outerFill}
      />
      <rect x="12.5" y="14" width="7" height="11" rx="2.5" fill={bottleCutout} />
      <rect x="14" y="11" width="4" height="2.2" rx="0.9" fill={bottleCutout} />
    </svg>
  );
}

export function FayaWordmark({
  variant = "color",
  size = 26,
}: {
  variant?: "color" | "ink" | "paper";
  size?: number;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <FayaMark variant={variant} size={size} />
      <span
        className={`font-display text-2xl font-bold uppercase tracking-[0.5px] leading-none ${
          variant === "paper" ? "text-text-inverse" : "text-text"
        }`}
      >
        Faya
      </span>
    </span>
  );
}
