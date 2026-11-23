/**
 * Carte dépôt (DESIGN_SYSTEM §4.1).
 * Toute la carte est un lien unique. Aucun bouton interne, aucune ombre décorative.
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  formatCapacityKg,
  formatDistance,
  formatFcfa,
  formatTimeHHMM,
} from "../../design/formatters";
import { normalizeStoreOpenStatus } from "../../design/statusStyles";
import { FreshnessStamp, OpenStatusChip } from "../../design/ui";
import type { PublicDepotList, PublicDepotOffer } from "./useDepots";

interface DepotCardProps {
  depot: PublicDepotList;
  serverNow?: string | null;
  selected?: boolean;
  activeBrandId?: string;
  activeCapacityKg?: string;
  onHighlight?: (depotId: string | null) => void;
  compact?: boolean;
}

function pickPrimaryOffer(
  offers: PublicDepotOffer[],
  activeBrandId?: string,
  activeCapacityKg?: string,
): PublicDepotOffer | null {
  if (offers.length === 0) return null;
  if (activeBrandId || activeCapacityKg) {
    const match = offers.find((offer) => {
      const brandOk = !activeBrandId || offer.product.brand.id === activeBrandId;
      const capOk =
        !activeCapacityKg ||
        Number.parseFloat(offer.product.capacity_kg) === Number.parseFloat(activeCapacityKg);
      return brandOk && capOk;
    });
    if (match) return match;
  }
  return offers.find((o) => o.operations.length > 0) ?? offers[0];
}

export function DepotCard({
  depot,
  serverNow,
  selected = false,
  activeBrandId,
  activeCapacityKg,
  onHighlight,
  compact = false,
}: DepotCardProps) {
  const { t, i18n } = useTranslation();
  const statusKey = normalizeStoreOpenStatus(depot.open_status);
  const isClosed = statusKey === "CLOSED";
  const primaryOffer = pickPrimaryOffer(depot.offers, activeBrandId, activeCapacityKg);

  const visibleOperations = primaryOffer ? primaryOffer.operations.slice(0, 2) : [];
  const freshnessSource = primaryOffer?.updated_at ?? depot.updated_at;

  const containerCls = selected
    ? "border-[3px] border-border-strong bg-bg"
    : isClosed
      ? "border-card border-border bg-surface-muted"
      : "border-card border-border-strong bg-bg hover:bg-surface-muted/40";

  return (
    <Link
      to={`/depots/${depot.id}`}
      onMouseEnter={() => onHighlight?.(depot.id)}
      onMouseLeave={() => onHighlight?.(null)}
      onFocus={() => onHighlight?.(depot.id)}
      className={`block rounded-lg p-3 transition-colors duration-150 ${containerCls}`}
    >
      {/* Ligne 1 : Nom du dépôt + Distance */}
      <div className="flex items-baseline justify-between gap-2">
        <h3
          className={`font-display text-xl font-bold uppercase tracking-[0.4px] leading-tight ${
            isClosed ? "text-text-secondary" : "text-text"
          }`}
        >
          {depot.name}
        </h3>
        {depot.distance_meters !== null && (
          <span className="shrink-0 font-mono text-sm font-medium tabular text-text">
            {formatDistance(depot.distance_meters, i18n.language)}
          </span>
        )}
      </div>

      {/* Ligne 2 : Quartier + Produit vedette */}
      <p className="mt-1 text-sm text-text-secondary">
        {primaryOffer ? (
          <>
            <span className="font-medium text-text">{primaryOffer.product.brand.name}</span>
            {" · "}
            <span>{formatCapacityKg(primaryOffer.product.capacity_kg, i18n.language)}</span>
            {depot.neighborhood ? ` · ${depot.neighborhood}` : ""}
          </>
        ) : (
          <span>{depot.neighborhood || depot.address}</span>
        )}
      </p>

      {/* Ligne 3 : Puce d'ouverture */}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <OpenStatusChip
          openStatus={depot.open_status}
          closingTime={depot.closing_time}
          reopensAt={depot.reopens_at}
        />
        {isClosed && (
          <span className="text-xs font-medium text-text-secondary">
            {t("store.reopensAt", { time: formatTimeHHMM(depot.reopens_at) })}
          </span>
        )}
      </div>

      {/* Ligne 4 : Prix par opération (jamais plus de 2 opérations sur la carte) */}
      {!compact && (
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          {visibleOperations.length > 0 ? (
            visibleOperations.map((op) => (
              <span key={op.operation_type} className="inline-flex items-baseline gap-1.5">
                <span className="text-text-secondary">{t(`operation.${op.operation_type}`)}</span>
                <span className="font-mono font-medium tabular text-text">
                  {formatFcfa(op.total_unit_price, i18n.language)}
                </span>
              </span>
            ))
          ) : (
            <span className="text-text-secondary">{t("store.noActiveOperations")}</span>
          )}
        </div>
      )}

      {/* Ligne 5 : Fraîcheur des données */}
      {!compact && (
        <div className="mt-2">
          <FreshnessStamp updatedAt={freshnessSource} serverNow={serverNow} />
        </div>
      )}
    </Link>
  );
}

/** Squelette de même hauteur que DepotCard (DESIGN_SYSTEM §4.9). */
export function DepotCardSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="rounded-lg border-card border-divider bg-bg p-3 space-y-2.5"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="h-6 w-2/3 rounded-sm bg-surface-muted animate-skeleton" />
        <div className="h-5 w-14 rounded-sm bg-surface-muted animate-skeleton" />
      </div>
      <div className="h-4 w-1/2 rounded-sm bg-surface-muted animate-skeleton" />
      <div className="h-7 w-40 rounded-sm bg-surface-muted animate-skeleton" />
      <div className="h-5 w-3/4 rounded-sm bg-surface-muted animate-skeleton" />
      <div className="h-4 w-44 rounded-sm bg-surface-muted animate-skeleton" />
    </div>
  );
}
