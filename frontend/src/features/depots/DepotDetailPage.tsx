/**
 * Fiche détaillée d'un dépôt (DESIGN_SYSTEM §4.2 & §4.3).
 * Les horaires et l'heure limite de commande sont visibles avant toute action.
 */

import {
  IconArrowLeft,
  IconChevronRight,
  IconMapPin,
  IconPhone,
  IconRoute,
} from "@tabler/icons-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  formatCapacityKg,
  formatFcfa,
  formatTimeHHMM,
} from "../../design/formatters";
import { normalizeStoreOpenStatus } from "../../design/statusStyles";
import {
  BottomSheet,
  Button,
  EmptyState,
  ErrorBanner,
  FreshnessStamp,
  OpenStatusChip,
} from "../../design/ui";
import { useNetworkStatus } from "../../shared/NetworkContext";
import { usePublicSettings } from "../settings/usePublicSettings";
import { useDepotDetail, type PublicDepotOffer } from "./useDepots";

const LazyDepotsMap = lazy(() => import("./DepotsMap"));

function offerMinPrice(offer: PublicDepotOffer): number | null {
  if (offer.operations.length === 0) return null;
  return Math.min(...offer.operations.map((op) => op.total_unit_price));
}

export function DepotDetailPage() {
  const { depotId } = useParams<{ depotId: string }>();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const { isOnline } = useNetworkStatus();

  const { data: settings } = usePublicSettings();
  const { data: depot, isLoading, error, refetch } = useDepotDetail(depotId);

  const [showMiniMap, setShowMiniMap] = useState(false);
  const [selectedOffer, setSelectedOffer] = useState<PublicDepotOffer | null>(null);

  const mapPoints = useMemo(
    () => (depot ? [depot] : []),
    [depot],
  );

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-4 space-y-4">
        <div className="h-8 w-24 rounded-sm bg-surface-muted animate-skeleton" />
        <div className="h-9 w-3/4 rounded-sm bg-surface-muted animate-skeleton" />
        <div className="h-7 w-48 rounded-sm bg-surface-muted animate-skeleton" />
        <div className="h-28 w-full rounded-lg bg-surface-muted animate-skeleton" />
        <div className="h-24 w-full rounded-lg bg-surface-muted animate-skeleton" />
      </div>
    );
  }

  if (error) {
    const isNotFound = error instanceof ApiError && error.status === 404;
    if (isNotFound) {
      return (
        <div className="mx-auto w-full max-w-xl px-4 py-6">
          <EmptyState
            title={t("store.notFoundTitle")}
            body={t("store.notFoundBody")}
            actionLabel={t("errors.backHome")}
            onAction={() => navigate("/")}
          />
        </div>
      );
    }
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-6">
        <ErrorBanner
          title={t("errors.serverTitle")}
          message={error instanceof Error ? error.message : t("errors.serverBody")}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  if (!depot) return null;

  const statusKey = normalizeStoreOpenStatus(depot.open_status);
  const isClosed = statusKey === "CLOSED";
  const cutoffMinutes = settings?.order_cutoff_before_close_minutes ?? 30;
  const openHHMM = formatTimeHHMM(depot.opening_time);
  const closeHHMM = formatTimeHHMM(depot.closing_time);
  const lastOrderHHMM = formatTimeHHMM(depot.last_order_time);
  const reopensHHMM = formatTimeHHMM(depot.reopens_at);

  const directionsUrl = `https://www.openstreetmap.org/?mlat=${depot.latitude}&mlon=${depot.longitude}#map=16/${depot.latitude}/${depot.longitude}`;
  const freshnessSource = depot.offers[0]?.updated_at ?? depot.updated_at;

  const canChoose = isOnline && depot.can_order && depot.offers.length > 0;
  let disabledReason: string | null = null;
  if (!isOnline) {
    disabledReason = t("net.actionNeedsConnection");
  } else if (isClosed) {
    disabledReason = t("store.closedExplanation", { time: reopensHHMM });
  } else if (!depot.can_order) {
    disabledReason = t("store.cutoffExplanation", { minutes: cutoffMinutes });
  } else if (depot.offers.length === 0) {
    disabledReason = t("store.noActiveOffers");
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-1 flex-col pb-28">
      {/* Barre supérieure retour + carte optionnelle */}
      <div className="flex items-center justify-between gap-2 px-4 pt-3 pb-2">
        <Link
          to="/"
          className="touch-target inline-flex items-center gap-1.5 rounded-md pr-3 text-base font-bold text-text hover:text-text-brand"
        >
          <IconArrowLeft size={20} stroke={1.75} aria-hidden="true" />
          <span>{t("nav.back")}</span>
        </Link>

        <button
          type="button"
          onClick={() => setShowMiniMap((v) => !v)}
          className="touch-target inline-flex items-center gap-1.5 rounded-md border-card border-border-strong px-3 text-sm font-bold text-text hover:bg-surface-muted"
        >
          <IconMapPin size={18} stroke={1.75} aria-hidden="true" />
          <span>{showMiniMap ? t("store.hideMap") : t("store.showMap")}</span>
        </button>
      </div>

      {/* Miniature carte chargée à la demande */}
      {showMiniMap && (
        <div className="mx-4 mb-3 h-52 overflow-hidden rounded-lg border-card border-border-strong">
          <Suspense
            fallback={<div className="h-full w-full bg-surface-muted animate-skeleton" />}
          >
            <LazyDepotsMap depots={mapPoints} selectedDepotId={depot.id} />
          </Suspense>
        </div>
      )}

      {/* En-tête identité + état d'ouverture + règle d'arrêt avant tout début de commande */}
      <header className="px-4 pb-4 border-b border-divider">
        <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px] text-text">
          {depot.name}
        </h1>

        <div className="mt-2.5 flex flex-wrap items-center gap-2">
          <OpenStatusChip
            openStatus={depot.open_status}
            closingTime={depot.closing_time}
            reopensAt={depot.reopens_at}
          />
          {!isClosed && (
            <span className="text-sm font-medium text-text-secondary">
              {t("store.lastOrderUntil", { time: lastOrderHHMM })}
            </span>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-base text-text-secondary">
            {depot.address}
            {depot.neighborhood ? ` · ${depot.neighborhood}` : ""}
          </p>
          <a
            href={directionsUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="touch-target inline-flex items-center gap-1.5 rounded-md border-card border-border-strong px-3 text-sm font-bold text-text hover:bg-surface-muted"
          >
            <IconRoute size={18} stroke={1.75} aria-hidden="true" />
            <span>{t("store.directions")}</span>
          </a>
        </div>

        {depot.description && (
          <p className="mt-2 text-sm text-text-secondary">{depot.description}</p>
        )}
      </header>

      {/* Informations pratiques */}
      <dl className="divide-y divide-divider border-b border-divider px-4 text-base">
        <div className="flex items-baseline justify-between gap-4 py-3">
          <dt className="shrink-0 text-sm font-bold text-text-secondary">
            {t("store.hoursLabel")}
          </dt>
          <dd className="text-right font-mono text-sm font-medium tabular text-text">
            {t("store.hoursEveryDay", { open: openHHMM, close: closeHHMM })}
          </dd>
        </div>

        <div className="flex items-center justify-between gap-4 py-3">
          <dt className="shrink-0 text-sm font-bold text-text-secondary">
            {t("store.contactLabel")}
          </dt>
          <dd className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium tabular text-text">
              {depot.phone}
            </span>
            <a
              href={`tel:${depot.phone}`}
              className="inline-flex min-h-10 items-center gap-1 rounded-md border-card border-border-strong px-2.5 text-sm font-bold text-text hover:bg-surface-muted"
            >
              <IconPhone size={16} stroke={1.75} aria-hidden="true" />
              <span>{t("store.call")}</span>
            </a>
          </dd>
        </div>

        <div className="flex items-baseline justify-between gap-4 py-3">
          <dt className="shrink-0 text-sm font-bold text-text-secondary">
            {t("store.pickupLabel")}
          </dt>
          <dd className="text-right text-sm text-text">{t("store.pickupPayment")}</dd>
        </div>
      </dl>

      {/* Section PRODUITS */}
      <section aria-labelledby="depot-products-heading" className="px-4 pt-4">
        <h2
          id="depot-products-heading"
          className="font-display text-xl font-bold uppercase tracking-[0.5px] text-text"
        >
          {t("store.productsTitle")}
        </h2>

        {depot.offers.length === 0 ? (
          <p className="mt-3 rounded-lg border-card border-border bg-surface-muted p-4 text-sm text-text-secondary">
            {t("store.noActiveOffers")}
          </p>
        ) : (
          <ul className="mt-3 space-y-2.5">
            {depot.offers.map((offer) => {
              const minPrice = offerMinPrice(offer);
              return (
                <li key={offer.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedOffer(offer)}
                    className="flex min-h-16 w-full items-center justify-between gap-3 rounded-lg border-card border-border-strong bg-bg px-3 py-3 text-left transition-colors duration-150 hover:bg-surface-muted"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="font-sans text-base font-bold text-text">
                        {offer.product.brand.name} ·{" "}
                        {formatCapacityKg(offer.product.capacity_kg, i18n.language)}
                      </p>
                      <p className="mt-0.5 text-sm text-text-secondary">
                        {offer.operations.length > 0
                          ? offer.operations
                              .map((op) => t(`operation.${op.operation_type}`))
                              .join(" · ")
                          : t("store.noActiveOperations")}
                      </p>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      {minPrice !== null && (
                        <span className="font-mono text-sm font-medium tabular text-text">
                          {t("store.fromPrice", {
                            price: formatFcfa(minPrice, i18n.language),
                          })}
                        </span>
                      )}
                      <IconChevronRight
                        size={20}
                        stroke={1.75}
                        className="text-text-secondary"
                        aria-hidden="true"
                      />
                    </div>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        <div className="mt-4">
          <FreshnessStamp
            updatedAt={freshnessSource}
            serverNow={settings?.server_now}
            suffix={t("store.availabilityDisclaimer")}
          />
        </div>
      </section>

      {/* Barre d'action collée en bas (zone du pouce, un seul bouton rouge principal par écran) */}
      <div className="fixed right-0 bottom-[calc(3.5rem+env(safe-area-inset-bottom))] left-0 z-30 border-t border-divider bg-bg px-4 py-3 lg:bottom-0 lg:left-[4.5rem]">
        <div className="mx-auto max-w-xl space-y-2">
          {disabledReason && (
            <p className="text-center text-sm font-medium text-text-secondary">
              {disabledReason}
            </p>
          )}
          <Button
            variant="primary"
            fullWidth
            disabled={!canChoose}
            onClick={() => {
              if (depot.offers.length > 0) {
                setSelectedOffer(depot.offers[0]);
              }
            }}
          >
            {t("store.chooseAction")}
          </Button>
        </div>
      </div>

      {/* Panneau détail des opérations et décomposition transparente des prix (DESIGN_SYSTEM §4.3 & §4.4) */}
      <BottomSheet
        open={Boolean(selectedOffer)}
        title={
          selectedOffer
            ? `${selectedOffer.product.brand.name} · ${formatCapacityKg(
                selectedOffer.product.capacity_kg,
                i18n.language,
              )}`
            : t("store.chooseOperationTitle")
        }
        onClose={() => setSelectedOffer(null)}
      >
        {selectedOffer && (
          <div className="space-y-4">
            {selectedOffer.notes && (
              <p className="rounded-md bg-surface-muted p-3 text-sm text-text-secondary">
                {selectedOffer.notes}
              </p>
            )}

            {selectedOffer.operations.length === 0 ? (
              <p className="text-sm text-text-secondary">{t("store.noActiveOperations")}</p>
            ) : (
              <div className="space-y-3">
                {selectedOffer.operations.map((op) => (
                  <div
                    key={op.operation_type}
                    className="rounded-md border-card border-border-strong bg-white p-3"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <h3 className="font-sans text-base font-bold text-text">
                        {t(`operation.${op.operation_type}`)}
                      </h3>
                      <span className="font-mono text-lg font-medium tabular text-text">
                        {formatFcfa(op.total_unit_price, i18n.language)}
                      </span>
                    </div>
                    <p className="mt-1 text-sm text-text-secondary">
                      {t(`operation.desc.${op.operation_type}`)}
                    </p>

                    {/* Décomposition transparente pour Première bouteille (jamais fusionnée, §4.4) */}
                    {op.operation_type === "FIRST_ACQUISITION" && (
                      <dl className="mt-2.5 space-y-1 border-t border-divider pt-2 text-sm">
                        <div className="flex justify-between">
                          <dt className="text-text-secondary">{t("operation.priceLines.gas")}</dt>
                          <dd className="font-mono tabular text-text">
                            {formatFcfa(op.gas_price, i18n.language)}
                          </dd>
                        </div>
                        {op.bottle_price > 0 && (
                          <div className="flex justify-between">
                            <dt className="text-text-secondary">
                              {t("operation.priceLines.bottle")}
                            </dt>
                            <dd className="font-mono tabular text-text">
                              {formatFcfa(op.bottle_price, i18n.language)}
                            </dd>
                          </div>
                        )}
                        {op.deposit_amount > 0 && (
                          <div className="flex justify-between">
                            <dt className="text-text-secondary">
                              {t("operation.priceLines.deposit")}
                            </dt>
                            <dd className="font-mono tabular text-text">
                              {formatFcfa(op.deposit_amount, i18n.language)}
                            </dd>
                          </div>
                        )}
                      </dl>
                    )}

                    {/* Marques vides acceptées en échange (DESIGN_SYSTEM §4.2 & §4.3) */}
                    {op.operation_type === "EXCHANGE" && (
                      <div className="mt-2.5 border-t border-divider pt-2">
                        <p className="text-xs font-bold text-text-secondary">
                          {t("store.exchangeAcceptedBrands")}
                        </p>
                        {selectedOffer.exchange_brands.length > 0 ? (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {selectedOffer.exchange_brands.map((brand) => (
                              <span
                                key={brand.id}
                                className="rounded-sm border-hair border-border bg-surface-muted px-2 py-0.5 text-xs font-bold text-text"
                              >
                                {brand.name}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-1 text-xs text-text-secondary">
                            {t("store.noExchangeBrands")}
                          </p>
                        )}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}

            <p className="rounded-md bg-surface-muted p-3 text-sm text-text-secondary">
              {t("store.orderingComingSoon")}
            </p>

            <div className="flex flex-col gap-2">
              <a
                href={`tel:${depot.phone}`}
                className="inline-flex min-h-14 w-full items-center justify-center gap-2 rounded-md bg-action px-4 font-display text-lg font-bold uppercase tracking-[0.5px] text-on-action hover:bg-action-pressed"
              >
                <IconPhone size={20} stroke={1.75} aria-hidden="true" />
                <span>
                  {t("store.call")} · {depot.phone}
                </span>
              </a>
              <Button variant="secondary" fullWidth onClick={() => setSelectedOffer(null)}>
                {t("errors.close")}
              </Button>
            </div>
          </div>
        )}
      </BottomSheet>
    </div>
  );
}
