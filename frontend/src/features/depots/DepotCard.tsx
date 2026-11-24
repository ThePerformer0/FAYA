/**
 * Carte dépôt — Esthétique éditoriale Faya.
 * Zéro bordure 1px grise autour de la carte : surface franche posée sur le sable +
 * barre d'accent gauche 4 px porteuse d'état + bande tarif teintée sans filet artificiel.
 */

import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import {
  formatCapacityKg,
  formatDistance,
  formatFcfa,
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
  const isClosingSoon = statusKey === "CLOSING_SOON";
  const primaryOffer = pickPrimaryOffer(depot.offers, activeBrandId, activeCapacityKg);

  const visibleOperations = primaryOffer ? primaryOffer.operations.slice(0, 2) : [];
  const freshnessSource =
    primaryOffer?.stock_updated_at ?? primaryOffer?.updated_at ?? depot.updated_at;

  const fullQty = primaryOffer?.available_full_quantity ?? 0;
  const newQty = primaryOffer?.available_new_quantity ?? 0;
  let stockBadge: { label: string; isOut: boolean } | null = null;
  if (primaryOffer) {
    if (fullQty > 0 && newQty > 0) {
      stockBadge = {
        label: t("store.stock.fullAndNew", { full: fullQty, newCount: newQty }),
        isOut: false,
      };
    } else if (fullQty > 0) {
      stockBadge = {
        label: t("store.stock.fullAvailable", { count: fullQty }),
        isOut: false,
      };
    } else if (newQty > 0) {
      stockBadge = {
        label: t("store.stock.noFullButNew", { count: newQty }),
        isOut: true,
      };
    } else {
      stockBadge = {
        label: t("store.stock.outOfStock"),
        isOut: true,
      };
    }
  }

  // Barre architecturale gauche 4 px (remplace les bordures 1px génériques tout autour)
  const accentBarCls = selected
    ? "border-l-4 border-action bg-card"
    : isClosingSoon
      ? "border-l-4 border-action bg-card hover:bg-price-band/70"
      : isClosed
        ? "border-l-4 border-ink-400 bg-surface-muted"
        : "border-l-4 border-ink-900 bg-card hover:bg-price-band/70";

  return (
    <Link
      to={`/depots/${depot.id}`}
      onMouseEnter={() => onHighlight?.(depot.id)}
      onMouseLeave={() => onHighlight?.(null)}
      onFocus={() => onHighlight?.(depot.id)}
      className={`block overflow-hidden rounded-r-sm transition-colors duration-150 ${accentBarCls}`}
    >
      {/* Corps haut */}
      <div className="px-4 pt-3.5 pb-3">
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

        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <OpenStatusChip
            openStatus={depot.open_status}
            closingTime={depot.closing_time}
            reopensAt={depot.reopens_at}
          />
          {stockBadge && (
            <span
              className={`inline-flex min-h-6 items-center rounded-sm px-2 py-0.5 font-mono text-xs font-medium tabular ${
                stockBadge.isOut
                  ? "bg-soon-bg text-soon"
                  : isClosed
                    ? "bg-card/70 text-text-secondary"
                    : "bg-price-band text-text"
              }`}
            >
              {stockBadge.label}
            </span>
          )}
        </div>
      </div>

      {/* Bande tarif teintée sans bordure grise artificielle */}
      {!compact && (
        <div
          className={`space-y-1.5 px-4 py-2.5 ${
            isClosed ? "bg-surface-muted" : "bg-price-band"
          }`}
        >
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
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
          <FreshnessStamp updatedAt={freshnessSource} serverNow={serverNow} />
        </div>
      )}
    </Link>
  );
}

/** Squelette de même géométrie que DepotCard. */
export function DepotCardSkeleton() {
  return (
    <div
      aria-hidden="true"
      className="overflow-hidden border-l-4 border-divider bg-card"
    >
      <div className="space-y-2.5 px-4 py-3.5">
        <div className="flex items-center justify-between gap-4">
          <div className="h-6 w-2/3 bg-surface-muted animate-skeleton" />
          <div className="h-5 w-14 bg-surface-muted animate-skeleton" />
        </div>
        <div className="h-4 w-1/2 bg-surface-muted animate-skeleton" />
        <div className="h-6 w-40 bg-surface-muted animate-skeleton" />
      </div>
      <div className="space-y-1.5 bg-price-band px-4 py-2.5">
        <div className="h-5 w-3/4 bg-surface-muted animate-skeleton" />
        <div className="h-4 w-44 bg-surface-muted animate-skeleton" />
      </div>
    </div>
  );
}
