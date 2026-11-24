/**
 * Styles complets des états Faya (Fusion A + B : Braise sur Sable).
 * Les classes sont littérales afin que Tailwind v4 les détecte statiquement.
 */

export const ORDER_STATUS = {
  PENDING: {
    icon: "hourglass-high",
    cls: "bg-price-band text-text border-hair border-dashed border-ink-600",
    labelKey: "order.status.pending",
  },
  CONFIRMED: {
    icon: "check",
    cls: "bg-open-bg text-open",
    labelKey: "order.status.confirmed",
  },
  PICKED_UP: {
    icon: "circle-check",
    cls: "bg-ink-900 text-text-inverse",
    labelKey: "order.status.pickedUp",
  },
  REFUSED: {
    icon: "circle-x",
    cls: "bg-danger-bg text-danger",
    labelKey: "order.status.refused",
  },
  EXPIRED: {
    icon: "clock-off",
    cls: "bg-closed-bg text-closed",
    labelKey: "order.status.expired",
  },
  CANCELLED: {
    icon: "ban",
    cls: "bg-closed-bg text-closed",
    labelKey: "order.status.cancelled",
  },
} as const;

export type StoreOpenStatusKey = "OPEN" | "CLOSING_SOON" | "CLOSED";

export const STORE_STATUS: Record<
  StoreOpenStatusKey,
  {
    glyph: "dot-full" | "dot-half" | "dot-empty";
    cls: string;
    labelKey: string;
  }
> = {
  OPEN: {
    glyph: "dot-full",
    cls: "bg-open-bg text-open",
    labelKey: "store.status.open",
  },
  CLOSING_SOON: {
    glyph: "dot-half",
    cls: "bg-soon-bg text-soon",
    labelKey: "store.status.closingSoon",
  },
  CLOSED: {
    glyph: "dot-empty",
    cls: "bg-closed-bg text-closed",
    labelKey: "store.status.closed",
  },
};

export function normalizeStoreOpenStatus(status: string): StoreOpenStatusKey {
  if (status === "OPEN" || status === "CLOSING_SOON" || status === "CLOSED") {
    return status;
  }
  return "CLOSED";
}
