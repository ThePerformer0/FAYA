/**
 * Styles complets des états Faya (DESIGN_SYSTEM §2.3, §2.4, §2.9).
 * Les classes sont littérales afin que Tailwind v4 les détecte statiquement.
 */

export const ORDER_STATUS = {
  PENDING: {
    icon: "hourglass-high",
    cls: "bg-bg text-text border-card border-dashed border-border-strong",
    labelKey: "order.status.pending",
  },
  CONFIRMED: {
    icon: "check",
    cls: "bg-ink-900 text-text-inverse",
    labelKey: "order.status.confirmed",
  },
  PICKED_UP: {
    icon: "circle-check",
    cls: "bg-bg text-text border-card border-solid border-border-strong",
    labelKey: "order.status.pickedUp",
  },
  REFUSED: {
    icon: "circle-x",
    cls: "bg-danger-bg text-danger",
    labelKey: "order.status.refused",
  },
  EXPIRED: {
    icon: "clock-off",
    cls: "bg-surface-muted text-text-secondary",
    labelKey: "order.status.expired",
  },
  CANCELLED: {
    icon: "ban",
    cls: "bg-surface-muted text-text-secondary",
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
    cls: "bg-bg text-text border-card border-solid border-border-strong",
    labelKey: "store.status.open",
  },
  CLOSING_SOON: {
    glyph: "dot-half",
    cls: "bg-ink-900 text-text-inverse",
    labelKey: "store.status.closingSoon",
  },
  CLOSED: {
    glyph: "dot-empty",
    cls: "bg-surface-muted text-text-secondary border-hair border-border",
    labelKey: "store.status.closed",
  },
};

export function normalizeStoreOpenStatus(status: string): StoreOpenStatusKey {
  if (status === "OPEN" || status === "CLOSING_SOON" || status === "CLOSED") {
    return status;
  }
  return "CLOSED";
}
