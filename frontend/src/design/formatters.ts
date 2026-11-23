/**
 * Formateurs Intl conformes à DESIGN_SYSTEM §6 (Africa/Douala, 24h, FCFA, distances).
 */

const PLATFORM_TIMEZONE = "Africa/Douala";

function resolveLocale(lang: string): string {
  return lang.startsWith("en") ? "en-US" : "fr-FR";
}

export function formatFcfa(amount: number, lang: string): string {
  const formatted = new Intl.NumberFormat(resolveLocale(lang), {
    maximumFractionDigits: 0,
  }).format(Math.round(amount));
  return `${formatted}\u00A0FCFA`;
}

export function formatDistance(meters: number, lang: string): string {
  const locale = resolveLocale(lang);
  if (meters < 1000) {
    return `${Math.round(meters)}\u00A0m`;
  }
  const km = meters / 1000;
  const formatted = new Intl.NumberFormat(locale, {
    minimumFractionDigits: km < 10 ? 1 : 0,
    maximumFractionDigits: km < 10 ? 1 : 0,
  }).format(km);
  return `${formatted}\u00A0km`;
}

export function formatCapacityKg(capacityKg: string | number, lang: string): string {
  const numeric = typeof capacityKg === "string" ? Number.parseFloat(capacityKg) : capacityKg;
  if (Number.isNaN(numeric)) {
    return `${capacityKg}\u00A0kg`;
  }
  const formatted = new Intl.NumberFormat(resolveLocale(lang), {
    minimumFractionDigits: Number.isInteger(numeric) ? 0 : 1,
    maximumFractionDigits: 2,
  }).format(numeric);
  return `${formatted}\u00A0kg`;
}

/** Convertit "08:00:00" ou "08:00" en "08:00" (format 24h). */
export function formatTimeHHMM(rawTime: string): string {
  if (!rawTime) return "";
  const parts = rawTime.split(":");
  if (parts.length >= 2) {
    return `${parts[0].padStart(2, "0")}:${parts[1].padStart(2, "0")}`;
  }
  return rawTime;
}

export function formatIsoTimeInPlatformTz(
  isoString: string,
  timeZone = PLATFORM_TIMEZONE,
): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone,
  }).format(date);
}

export function formatShortDate(
  isoString: string,
  lang: string,
  timeZone = PLATFORM_TIMEZONE,
): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat(resolveLocale(lang), {
    day: "numeric",
    month: "short",
    timeZone,
  }).format(date);
}

export interface FreshnessLevel {
  tier: "recent" | "check" | "stale";
  minutes: number;
}

export function computeFreshness(
  updatedAtIso: string,
  referenceNowIso?: string | null,
): FreshnessLevel {
  const updatedMs = new Date(updatedAtIso).getTime();
  const nowMs = referenceNowIso ? new Date(referenceNowIso).getTime() : Date.now();
  if (Number.isNaN(updatedMs) || Number.isNaN(nowMs)) {
    return { tier: "stale", minutes: 120 };
  }
  const diffMin = Math.max(0, Math.floor((nowMs - updatedMs) / 60_000));
  if (diffMin <= 15) {
    return { tier: "recent", minutes: diffMin };
  }
  if (diffMin <= 60) {
    return { tier: "check", minutes: diffMin };
  }
  return { tier: "stale", minutes: diffMin };
}
