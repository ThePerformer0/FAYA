/**
 * Composants de base Faya (DESIGN_SYSTEM §4.0, §4.8, §4.9).
 * Aucune couleur Tailwind par défaut, aucun dégradé, aucune ombre décorative.
 */

import {
  IconAlertTriangle,
  IconCheck,
  IconClock,
  IconWifiOff,
  IconX,
} from "@tabler/icons-react";
import {
  forwardRef,
  useEffect,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";

import { FayaMark } from "./FayaLogo";
import { computeFreshness, formatIsoTimeInPlatformTz, formatTimeHHMM } from "./formatters";
import { normalizeStoreOpenStatus, STORE_STATUS } from "./statusStyles";

/* === Bouton === */

export type ButtonVariant = "primary" | "secondary" | "danger" | "link";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  fullWidth?: boolean;
  isLoading?: boolean;
  loadingLabel?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    fullWidth = false,
    isLoading = false,
    loadingLabel,
    disabled,
    className = "",
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  const isDisabled = Boolean(disabled || isLoading);
  const widthCls = fullWidth ? "w-full" : "";

  let variantCls = "";
  if (isDisabled && variant !== "link") {
    variantCls =
      "min-h-14 rounded-md bg-surface-muted text-text-secondary border-hair border-border cursor-not-allowed";
  } else if (variant === "primary") {
    variantCls =
      "min-h-14 rounded-md bg-action text-on-action active:bg-action-pressed hover:bg-action-pressed font-display font-bold text-lg uppercase tracking-[0.5px]";
  } else if (variant === "danger") {
    variantCls =
      "min-h-14 rounded-md bg-danger text-on-action font-display font-bold text-lg uppercase tracking-[0.5px]";
  } else if (variant === "secondary") {
    variantCls =
      "min-h-12 rounded-md bg-transparent text-text border-card border-border-strong hover:bg-surface-muted font-sans font-bold text-base";
  } else {
    variantCls =
      "min-h-12 px-2 bg-transparent text-text-brand underline font-sans font-medium text-base hover:text-text";
  }

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      className={`inline-flex items-center justify-center gap-2 px-4 transition-colors duration-150 ${variantCls} ${widthCls} ${className}`}
      {...rest}
    >
      {isLoading ? (loadingLabel ?? "…") : children}
    </button>
  );
});

/* === Champ de formulaire === */

interface TextFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  id: string;
  label: string;
  hint?: string;
  error?: string;
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { id, label, hint, error, className = "", ...rest },
  ref,
) {
  const errorId = error ? `${id}-error` : undefined;
  const hintId = hint && !error ? `${id}-hint` : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-bold text-text">
        {label}
      </label>
      <input
        ref={ref}
        id={id}
        aria-invalid={error ? "true" : "false"}
        aria-describedby={errorId ?? hintId}
        className={`h-12 w-full rounded-md bg-white px-3 text-base text-text placeholder:text-text-muted focus:outline-none ${
          error
            ? "border-2 border-danger"
            : "border-card border-ink-600 focus:border-border-strong"
        } ${className}`}
        {...rest}
      />
      {error ? (
        <p id={errorId} role="alert" className="flex items-start gap-1.5 text-sm font-medium text-danger">
          <IconAlertTriangle size={18} stroke={1.75} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </p>
      ) : hint ? (
        <p id={hintId} className="text-xs text-text-secondary">
          {hint}
        </p>
      ) : null}
    </div>
  );
});

/* === Glyphes d'ouverture (SVG maison en currentColor, DESIGN_SYSTEM §2.4 & §7.2) === */

export function OpenStatusGlyph({ glyph }: { glyph: "dot-full" | "dot-half" | "dot-empty" }) {
  if (glyph === "dot-full") {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className="shrink-0">
        <circle cx="6" cy="6" r="5" fill="currentColor" />
      </svg>
    );
  }
  if (glyph === "dot-half") {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className="shrink-0">
        <circle cx="6" cy="6" r="4.75" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M6 1.25 A4.75 4.75 0 0 0 6 10.75 Z" fill="currentColor" />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className="shrink-0">
      <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

/* === Puce d'ouverture dépôt === */

interface OpenStatusChipProps {
  openStatus: string;
  closingTime: string;
  reopensAt: string;
}

export function OpenStatusChip({ openStatus, closingTime, reopensAt }: OpenStatusChipProps) {
  const { t } = useTranslation();
  const normalized = normalizeStoreOpenStatus(openStatus);
  const spec = STORE_STATUS[normalized];
  const displayTime =
    normalized === "CLOSED" ? formatTimeHHMM(reopensAt) : formatTimeHHMM(closingTime);

  return (
    <span
      className={`inline-flex min-h-7 items-center gap-1.5 rounded-sm px-2 py-0.5 text-sm font-bold ${spec.cls}`}
    >
      <OpenStatusGlyph glyph={spec.glyph} />
      <span>{t(spec.labelKey, { time: displayTime })}</span>
    </span>
  );
}

/* === Pastille de filtre (hauteur visible 40 px, zone tactile 48 px, icône check si sélectionnée) === */

interface FilterChipProps {
  label: string;
  selected: boolean;
  onClick: () => void;
}

export function FilterChip({ label, selected, onClick }: FilterChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className="inline-flex min-h-12 shrink-0 items-center py-1"
    >
      <span
        className={`inline-flex h-10 items-center gap-1.5 rounded-md border-card border-border-strong px-3 text-sm font-bold transition-colors duration-150 ${
          selected
            ? "bg-ink-900 text-text-inverse"
            : "bg-bg text-text hover:bg-surface-muted"
        }`}
      >
        {selected && <IconCheck size={16} stroke={2} aria-hidden="true" />}
        <span>{label}</span>
      </span>
    </button>
  );
}

/* === Fraîcheur des données (DESIGN_SYSTEM §4.8) === */

interface FreshnessStampProps {
  updatedAt: string;
  serverNow?: string | null;
  suffix?: string;
}

export function FreshnessStamp({ updatedAt, serverNow, suffix }: FreshnessStampProps) {
  const { t } = useTranslation();
  const { tier, minutes } = computeFreshness(updatedAt, serverNow);

  if (tier === "recent") {
    const label =
      minutes < 1
        ? t("freshness.justNow")
        : t("freshness.recent", { minutes });
    return (
      <p className="flex items-center gap-1.5 text-xs text-text-muted">
        <IconClock size={14} stroke={1.75} className="shrink-0" aria-hidden="true" />
        <span>
          {label}
          {suffix ? ` · ${suffix}` : ""}
        </span>
      </p>
    );
  }

  if (tier === "check") {
    return (
      <p className="flex items-center gap-1.5 text-xs font-bold text-text">
        <IconClock size={14} stroke={1.75} className="shrink-0" aria-hidden="true" />
        <span>
          {t("freshness.check", { minutes })}
          {suffix ? ` · ${suffix}` : ""}
        </span>
      </p>
    );
  }

  const hours = Math.max(1, Math.floor(minutes / 60));
  const days = Math.floor(hours / 24);
  const staleText =
    days >= 1
      ? t("freshness.staleDays", { days })
      : t("freshness.staleHours", { hours });

  return (
    <p className="flex items-center gap-1.5 text-xs font-bold text-text">
      <IconAlertTriangle size={14} stroke={1.75} className="shrink-0" aria-hidden="true" />
      <span>
        {staleText}
        {suffix ? ` · ${suffix}` : ""}
      </span>
    </p>
  );
}

/* === Bandeau d'erreur (DESIGN_SYSTEM §4.9) === */

interface ErrorBannerProps {
  title?: string;
  message: string;
  reference?: string;
  onRetry?: () => void;
}

export function ErrorBanner({ title, message, reference, onRetry }: ErrorBannerProps) {
  const { t } = useTranslation();

  return (
    <div
      role="alert"
      className="rounded-md border-hair border-danger bg-danger-bg p-3 text-danger"
    >
      <div className="flex items-start gap-2">
        <IconAlertTriangle size={20} stroke={1.75} className="mt-0.5 shrink-0" aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-1">
          {title && <p className="text-sm font-bold">{title}</p>}
          <p className="text-sm">{message}</p>
          {reference && <p className="font-mono text-xs tabular">{reference}</p>}
        </div>
      </div>
      {onRetry && (
        <div className="mt-3">
          <Button variant="secondary" onClick={onRetry}>
            {t("errors.retry")}
          </Button>
        </div>
      )}
    </div>
  );
}

/* === État vide (DESIGN_SYSTEM §4.9 : marque Faya ink-300 64px) === */

interface EmptyStateProps {
  title: string;
  body: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({ title, body, actionLabel, onAction }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border-card border-border bg-bg px-6 py-10 text-center">
      <FayaMark variant="muted" size={64} />
      <h2 className="mt-4 font-display text-xl font-bold uppercase tracking-[0.5px] text-text">
        {title}
      </h2>
      <p className="mt-2 max-w-sm text-base text-text-secondary">{body}</p>
      {actionLabel && onAction && (
        <div className="mt-5">
          <Button variant="secondary" onClick={onAction}>
            {actionLabel}
          </Button>
        </div>
      )}
    </div>
  );
}

/* === Bandeau hors ligne (DESIGN_SYSTEM §4.8) === */

interface OfflineBannerProps {
  isOnline: boolean;
  justRestored: boolean;
  lastSyncIso: string | null;
}

export function OfflineBanner({ isOnline, justRestored, lastSyncIso }: OfflineBannerProps) {
  const { t } = useTranslation();

  if (isOnline && !justRestored) {
    return null;
  }

  if (isOnline && justRestored) {
    return (
      <div
        role="status"
        className="flex min-h-10 items-center justify-center gap-2 border-b border-offline-border bg-offline-bg px-4 text-sm font-bold text-text"
      >
        <IconCheck size={18} stroke={1.75} aria-hidden="true" />
        <span>{t("net.restored")}</span>
      </div>
    );
  }

  const formattedTime = lastSyncIso ? formatIsoTimeInPlatformTz(lastSyncIso) : "";
  return (
    <div
      role="status"
      className="flex min-h-10 items-center justify-center gap-2 border-b border-offline-border bg-offline-bg px-4 text-sm font-medium text-text"
    >
      <IconWifiOff size={18} stroke={1.75} aria-hidden="true" />
      <span>
        {formattedTime
          ? t("net.offline", { time: formattedTime })
          : t("net.offlineNoTime")}
      </span>
    </div>
  );
}

/* === Panneau du bas (BottomSheet, DESIGN_SYSTEM §4.0) === */

interface BottomSheetProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function BottomSheet({ open, title, onClose, children }: BottomSheetProps) {
  const { t } = useTranslation();

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink-900/40 md:items-center md:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="max-h-[85dvh] w-full max-w-lg overflow-y-auto rounded-t-xl bg-bg p-4 pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-sheet md:rounded-xl md:p-6">
        <div className="mx-auto mb-3 h-1 w-8 rounded-full bg-ink-300 md:hidden" aria-hidden="true" />
        <div className="flex items-center justify-between gap-2 pb-3 border-b border-divider">
          <h2 className="font-display text-xl font-bold uppercase tracking-[0.5px] text-text">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("errors.close")}
            className="touch-target inline-flex items-center justify-center rounded-md text-text hover:bg-surface-muted"
          >
            <IconX size={22} stroke={1.75} aria-hidden="true" />
          </button>
        </div>
        <div className="mt-4">{children}</div>
      </div>
    </div>
  );
}
