/**
 * Fiche détaillée d'un dépôt — Esthétique éditoriale architecturale (« Braise sur Sable »).
 * Le bouton « Itinéraire » ouvre la carte intégrée (chargée à la demande) avec la position du dépôt
 * + demande/affiche la position du client si autorisée, et propose le guidage Google Maps en option.
 */

import {
  IconArrowLeft,
  IconCheck,
  IconChevronRight,
  IconCurrentLocation,
  IconExternalLink,
  IconMinus,
  IconPhone,
  IconPlus,
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
  FilterChip,
  FreshnessStamp,
  OpenStatusChip,
} from "../../design/ui";
import { useNetworkStatus } from "../../shared/NetworkContext";
import { useAuth } from "../auth/AuthContext";
import { useCreateOrder } from "../orders/useOrders";
import { usePublicSettings } from "../settings/usePublicSettings";
import { useDepotDetail, type OperationType, type PublicDepotOffer } from "./useDepots";

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
  const { user } = useAuth();

  const { data: settings } = usePublicSettings();
  const { data: depot, isLoading, error, refetch } = useDepotDetail(depotId);
  const createOrderMutation = useCreateOrder();

  const [showDirectionsMap, setShowDirectionsMap] = useState(false);
  const [userCoords, setUserCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [geoStatus, setGeoStatus] = useState<"idle" | "locating" | "granted" | "denied" | "unsupported">("idle");
  const [selectedOffer, setSelectedOffer] = useState<PublicDepotOffer | null>(null);
  const [selectedOpType, setSelectedOpType] = useState<OperationType | null>(null);
  const [selectedExchangeBrandId, setSelectedExchangeBrandId] = useState<string>("");
  const [orderQuantity, setOrderQuantity] = useState<number>(1);
  const [orderError, setOrderError] = useState<string | null>(null);

  const openOfferSheet = (offer: PublicDepotOffer) => {
    setSelectedOffer(offer);
    setOrderError(null);
    setOrderQuantity(1);
    setSelectedExchangeBrandId(offer.exchange_brands[0]?.id ?? "");
    const firstAvailableOp =
      offer.operations.find((op) =>
        op.operation_type === "FIRST_ACQUISITION"
          ? offer.available_new_quantity > 0 || offer.available_full_quantity > 0
          : offer.available_full_quantity > 0,
      ) ?? offer.operations[0];
    setSelectedOpType(firstAvailableOp?.operation_type ?? null);
  };

  const mapPoints = useMemo(
    () => (depot ? [depot] : []),
    [depot],
  );

  const requestUserLocation = () => {
    if (!("geolocation" in navigator)) {
      setGeoStatus("unsupported");
      return;
    }
    setGeoStatus("locating");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setUserCoords({
          lat: Number(position.coords.latitude.toFixed(6)),
          lng: Number(position.coords.longitude.toFixed(6)),
        });
        setGeoStatus("granted");
      },
      () => {
        setGeoStatus("denied");
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 },
    );
  };

  const handleToggleDirections = () => {
    const nextOpen = !showDirectionsMap;
    setShowDirectionsMap(nextOpen);
    if (nextOpen && !userCoords && geoStatus === "idle") {
      requestUserLocation();
    }
  };

  if (isLoading) {
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-4 space-y-4">
        <div className="h-36 w-full bg-surface-muted animate-skeleton" />
        <div className="h-24 w-full bg-card animate-skeleton" />
        <div className="h-24 w-full bg-card animate-skeleton" />
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

  const googleMapsUrl = userCoords
    ? `https://www.google.com/maps/dir/?api=1&origin=${userCoords.lat},${userCoords.lng}&destination=${depot.latitude},${depot.longitude}`
    : `https://www.google.com/maps/dir/?api=1&destination=${depot.latitude},${depot.longitude}`;
  const latestStockIso = depot.offers.reduce<string | null>((latest, offer) => {
    if (!offer.stock_updated_at) return latest;
    if (!latest || offer.stock_updated_at > latest) return offer.stock_updated_at;
    return latest;
  }, null);
  const freshnessSource = latestStockIso ?? depot.offers[0]?.updated_at ?? depot.updated_at;

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
    <div className="flex flex-1 flex-col pb-28">
      {/* En-tête charbon franc */}
      <header className="bg-header-bg text-text-inverse">
        <div className="mx-auto w-full max-w-xl px-4 pt-2 pb-5">
          <div className="flex items-center justify-between gap-2">
            <Link
              to="/"
              className="touch-target inline-flex items-center gap-1.5 pr-3 text-sm font-bold text-text-inverse hover:text-action"
            >
              <IconArrowLeft size={20} stroke={1.75} aria-hidden="true" />
              <span>{t("nav.back")}</span>
            </Link>
          </div>

          <h1 className="mt-1 font-display text-2xl font-bold uppercase tracking-[0.5px] text-text-inverse">
            {depot.name}
          </h1>

          <p className="mt-1 text-sm text-text-inverse-muted">
            {depot.address}
            {depot.neighborhood ? ` · ${depot.neighborhood}` : ""}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <OpenStatusChip
              openStatus={depot.open_status}
              closingTime={depot.closing_time}
              reopensAt={depot.reopens_at}
            />
            {!isClosed && (
              <span className="text-xs font-medium text-text-inverse-muted">
                {t("store.lastOrderUntil", { time: lastOrderHHMM })}
              </span>
            )}
          </div>

          {depot.description && (
            <p className="mt-2.5 text-sm text-text-inverse-muted">{depot.description}</p>
          )}
        </div>
      </header>

      {/* Contenu éditorial sur fond sable chaud */}
      <div className="mx-auto w-full max-w-xl space-y-5 px-4 pt-4">
        {/* Boutons rapides Appeler / Itinéraire */}
        <div className="grid grid-cols-2 gap-2.5">
          <a
            href={`tel:${depot.phone}`}
            className="touch-target inline-flex items-center justify-center gap-2 rounded-sm bg-card px-4 py-3 text-base font-bold text-text hover:bg-price-band"
          >
            <IconPhone size={20} stroke={1.75} className="text-text-brand" aria-hidden="true" />
            <span>{t("store.call")}</span>
          </a>

          <button
            type="button"
            onClick={handleToggleDirections}
            aria-expanded={showDirectionsMap}
            className={`touch-target inline-flex items-center justify-center gap-2 rounded-sm px-4 py-3 text-base font-bold transition-colors duration-150 ${
              showDirectionsMap
                ? "bg-ink-900 text-text-inverse"
                : "bg-card text-text hover:bg-price-band"
            }`}
          >
            <IconRoute
              size={20}
              stroke={1.75}
              className={showDirectionsMap ? "text-action" : "text-text-brand"}
              aria-hidden="true"
            />
            <span>{showDirectionsMap ? t("store.closeDirections") : t("store.directions")}</span>
          </button>
        </div>

        {/* Panneau Itinéraire intégré (dépôt + position client si autorisée, chargé à la demande) */}
        {showDirectionsMap && (
          <div className="relative z-0 isolate space-y-2.5 border-l-4 border-action bg-card">
            <div className="relative z-0 isolate h-64 w-full overflow-hidden bg-surface-muted">
              <Suspense
                fallback={<div className="h-full w-full bg-surface-muted animate-skeleton" />}
              >
                <LazyDepotsMap
                  depots={mapPoints}
                  selectedDepotId={depot.id}
                  userCoords={userCoords}
                />
              </Suspense>
            </div>

            <div className="space-y-2.5 px-4 pb-4">
              {geoStatus === "locating" && (
                <p className="text-xs font-medium text-text-secondary">{t("geo.locating")}</p>
              )}

              {geoStatus === "granted" && userCoords && (
                <p className="text-xs font-medium text-open">{t("store.yourPositionShown")}</p>
              )}

              {(geoStatus === "denied" || geoStatus === "idle") && !userCoords && (
                <div className="flex flex-wrap items-center justify-between gap-2 bg-price-band px-3 py-2 text-xs text-text-secondary">
                  <span>{t("store.shareLocationPrompt")}</span>
                  <button
                    type="button"
                    onClick={requestUserLocation}
                    className="inline-flex min-h-9 items-center gap-1.5 rounded-sm bg-ink-900 px-3 text-xs font-bold text-text-inverse hover:bg-ink-700"
                  >
                    <IconCurrentLocation size={14} stroke={2} aria-hidden="true" />
                    <span>{t("store.showMyPosition")}</span>
                  </button>
                </div>
              )}

              {geoStatus === "unsupported" && (
                <p className="text-xs text-text-secondary">{t("geo.unsupported")}</p>
              )}

              <a
                href={googleMapsUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-sm bg-surface-muted px-3 text-sm font-bold text-text hover:bg-border"
              >
                <IconExternalLink size={17} stroke={1.75} aria-hidden="true" />
                <span>{t("store.openInGoogleMaps")}</span>
              </a>
            </div>
          </div>
        )}

        {/* Informations pratiques posées directement à même le sable */}
        <dl className="divide-y divide-border text-base">
          <div className="flex items-baseline justify-between gap-4 py-3">
            <dt className="shrink-0 text-xs font-bold uppercase tracking-[0.5px] text-text-secondary">
              {t("store.hoursLabel")}
            </dt>
            <dd className="text-right font-mono text-sm font-medium tabular text-text">
              {t("store.hoursEveryDay", { open: openHHMM, close: closeHHMM })}
            </dd>
          </div>

          <div className="flex items-baseline justify-between gap-4 py-3">
            <dt className="shrink-0 text-xs font-bold uppercase tracking-[0.5px] text-text-secondary">
              {t("store.contactLabel")}
            </dt>
            <dd className="text-right font-mono text-sm font-medium tabular text-text">
              {depot.phone}
            </dd>
          </div>

          <div className="flex items-baseline justify-between gap-4 py-3">
            <dt className="shrink-0 text-xs font-bold uppercase tracking-[0.5px] text-text-secondary">
              {t("store.pickupLabel")}
            </dt>
            <dd className="text-right text-sm text-text">{t("store.pickupPayment")}</dd>
          </div>
        </dl>

        {/* Section PRODUITS : bloc continu façon carte tarifaire imprimée */}
        <section aria-labelledby="depot-products-heading" className="pt-1">
          <h2
            id="depot-products-heading"
            className="font-display text-xl font-bold uppercase tracking-[0.6px] text-text"
          >
            {t("store.productsTitle")}
          </h2>

          {depot.offers.length === 0 ? (
            <p className="mt-2.5 bg-surface-muted p-4 text-sm text-text-secondary">
              {t("store.noActiveOffers")}
            </p>
          ) : (
            <ul className="mt-2.5 divide-y divide-divider border-l-4 border-ink-900 bg-card">
              {depot.offers.map((offer) => {
                const minPrice = offerMinPrice(offer);
                const fullQty = offer.available_full_quantity;
                const newQty = offer.available_new_quantity;
                const stockLabel =
                  fullQty > 0 && newQty > 0
                    ? t("store.stock.fullAndNew", { full: fullQty, newCount: newQty })
                    : fullQty > 0
                      ? t("store.stock.fullAvailable", { count: fullQty })
                      : newQty > 0
                        ? t("store.stock.noFullButNew", { count: newQty })
                        : t("store.stock.outOfStock");
                const isLowOrOut = fullQty === 0;
                return (
                  <li key={offer.id}>
                    <button
                      type="button"
                      onClick={() => openOfferSheet(offer)}
                      className="flex min-h-16 w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition-colors duration-150 hover:bg-price-band"
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
                        <p
                          className={`mt-1 font-mono text-xs font-medium tabular ${
                            isLowOrOut ? "text-soon" : "text-text-secondary"
                          }`}
                        >
                          {stockLabel}
                        </p>
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        {minPrice !== null && (
                          <span className="font-mono text-sm font-medium tabular text-text-brand">
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
      </div>

      {/* Barre d'action collée en bas (charbon) */}
      <div className="fixed right-0 bottom-[calc(3.5rem+var(--safe-bottom))] left-0 z-30 bg-header-bg px-4 py-3 lg:bottom-0 lg:left-[4.5rem]">
        <div className="mx-auto max-w-xl space-y-2">
          {disabledReason && (
            <p className="text-center text-xs font-medium text-text-inverse-muted">
              {disabledReason}
            </p>
          )}
          <Button
            variant="primary"
            fullWidth
            disabled={!canChoose}
            onClick={() => {
              if (depot.offers.length > 0) {
                openOfferSheet(depot.offers[0]);
              }
            }}
          >
            {t("store.chooseAction")}
          </Button>
        </div>
      </div>

      {/* Panneau de commande pour retrait : sélection opération, marque vide, quantité et total FCFA */}
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
        {selectedOffer && (() => {
          const maxPlatformQty = settings?.max_quantity_per_order ?? 3;
          const activeOperation =
            selectedOffer.operations.find((op) => op.operation_type === selectedOpType) ?? null;
          const stockForSelectedOp = activeOperation
            ? activeOperation.operation_type === "FIRST_ACQUISITION"
              ? Math.max(selectedOffer.available_new_quantity, selectedOffer.available_full_quantity)
              : selectedOffer.available_full_quantity
            : 0;
          const effectiveMaxQty = Math.max(1, Math.min(maxPlatformQty, stockForSelectedOp || 1));
          const safeQty = Math.min(orderQuantity, effectiveMaxQty);
          const isExchange = activeOperation?.operation_type === "EXCHANGE";
          const needsExchangeBrand = isExchange && !selectedExchangeBrandId;
          const totalAmount = activeOperation ? activeOperation.total_unit_price * safeQty : 0;

          const canSubmitOrder =
            Boolean(activeOperation) &&
            isOnline &&
            depot.can_order &&
            stockForSelectedOp >= safeQty &&
            !needsExchangeBrand &&
            user?.role === "CUSTOMER";

          const handleSubmitOrder = async () => {
            if (!activeOperation || !depot) return;
            if (!user) {
              navigate("/login", { state: { from: `/depots/${depot.id}` } });
              return;
            }
            if (needsExchangeBrand) {
              setOrderError(t("store.exchangeBrandRequired"));
              return;
            }
            setOrderError(null);
            try {
              await createOrderMutation.mutateAsync({
                depot_id: depot.id,
                product_id: selectedOffer.product.id,
                operation_type: activeOperation.operation_type,
                quantity: safeQty,
                ...(isExchange ? { exchange_brand_id: selectedExchangeBrandId } : {}),
              });
              setSelectedOffer(null);
              navigate("/orders", { state: { created: true } });
            } catch (err) {
              setOrderError(err instanceof Error ? err.message : t("errors.serverBody"));
            }
          };

          return (
            <div className="space-y-4">
              {/* Disponibilité réelle (pleines / neuves uniquement, jamais vides) */}
              <div className="grid grid-cols-2 gap-2.5">
                <div className="bg-card px-3.5 py-2.5">
                  <p className="text-xs font-bold uppercase tracking-[0.3px] text-text-secondary">
                    {t("store.stock.fullLabel")}
                  </p>
                  <p
                    className={`mt-1 font-mono text-xl font-medium tabular ${
                      selectedOffer.available_full_quantity > 0 ? "text-text" : "text-soon"
                    }`}
                  >
                    {selectedOffer.available_full_quantity}
                  </p>
                </div>
                <div className="bg-card px-3.5 py-2.5">
                  <p className="text-xs font-bold uppercase tracking-[0.3px] text-text-secondary">
                    {t("store.stock.newLabel")}
                  </p>
                  <p
                    className={`mt-1 font-mono text-xl font-medium tabular ${
                      selectedOffer.available_new_quantity > 0 ? "text-text" : "text-text-secondary"
                    }`}
                  >
                    {selectedOffer.available_new_quantity}
                  </p>
                </div>
              </div>

              {selectedOffer.stock_updated_at && (
                <FreshnessStamp
                  updatedAt={selectedOffer.stock_updated_at}
                  serverNow={settings?.server_now}
                />
              )}

              {selectedOffer.notes && (
                <p className="border-l-4 border-ink-900 bg-card px-3.5 py-2.5 text-sm text-text-secondary">
                  {selectedOffer.notes}
                </p>
              )}

              {orderError && <ErrorBanner message={orderError} />}

              {selectedOffer.operations.length === 0 ? (
                <p className="text-sm text-text-secondary">{t("store.noActiveOperations")}</p>
              ) : (
                <div className="space-y-2">
                  <p className="text-xs font-bold uppercase tracking-[0.4px] text-text-secondary">
                    {t("store.selectOperationPrompt")}
                  </p>
                  <div className="space-y-2">
                    {selectedOffer.operations.map((op) => {
                      const opStock =
                        op.operation_type === "FIRST_ACQUISITION"
                          ? Math.max(
                              selectedOffer.available_new_quantity,
                              selectedOffer.available_full_quantity,
                            )
                          : selectedOffer.available_full_quantity;
                      const opOutOfStock = opStock === 0;
                      const isSelected = op.operation_type === selectedOpType;
                      return (
                        <button
                          key={op.operation_type}
                          type="button"
                          onClick={() => {
                            setSelectedOpType(op.operation_type);
                            setOrderQuantity(1);
                            setOrderError(null);
                          }}
                          className={`block w-full border-l-4 p-3.5 text-left transition-colors duration-150 ${
                            isSelected
                              ? "border-action bg-card"
                              : "border-ink-300 bg-card/75 hover:bg-card"
                          }`}
                        >
                          <div className="flex items-baseline justify-between gap-2">
                            <span className="inline-flex items-center gap-2 font-sans text-base font-bold text-text">
                              {isSelected && (
                                <IconCheck size={16} stroke={2.4} className="text-action" aria-hidden="true" />
                              )}
                              <span>{t(`operation.${op.operation_type}`)}</span>
                            </span>
                            <span className="font-mono text-lg font-medium tabular text-text-brand">
                              {formatFcfa(op.total_unit_price, i18n.language)}
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-text-secondary">
                            {t(`operation.desc.${op.operation_type}`)}
                          </p>
                          {opOutOfStock && (
                            <p className="mt-1 text-xs font-bold text-soon">
                              {t("store.stock.unavailableForOperation")}
                            </p>
                          )}

                          {op.operation_type === "FIRST_ACQUISITION" && isSelected && (
                            <dl className="mt-2.5 space-y-1 bg-price-band px-3 py-2 text-xs">
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
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Marque de la bouteille vide rapportée (obligatoire pour Échange) */}
              {isExchange && (
                <div className="space-y-2 bg-card p-3.5">
                  <p className="text-xs font-bold uppercase tracking-[0.3px] text-text-secondary">
                    {t("store.selectExchangeBrandPrompt")}
                  </p>
                  {selectedOffer.exchange_brands.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {selectedOffer.exchange_brands.map((brand) => (
                        <FilterChip
                          key={brand.id}
                          label={brand.name}
                          selected={selectedExchangeBrandId === brand.id}
                          onClick={() => {
                            setSelectedExchangeBrandId(brand.id);
                            setOrderError(null);
                          }}
                        />
                      ))}
                    </div>
                  ) : (
                    <p className="text-xs text-soon">{t("store.noExchangeBrands")}</p>
                  )}
                </div>
              )}

              {/* Sélecteur de quantité + Total transparent */}
              {activeOperation && stockForSelectedOp > 0 && (
                <div className="space-y-3 bg-card p-3.5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-xs font-bold uppercase tracking-[0.3px] text-text-secondary">
                        {t("store.quantityLabel")}
                      </p>
                      <p className="text-xs text-text-muted">
                        {t("store.quantityMaxHint", { max: maxPlatformQty })}
                      </p>
                    </div>

                    <div className="inline-flex items-center gap-2">
                      <button
                        type="button"
                        aria-label="-"
                        disabled={safeQty <= 1}
                        onClick={() => setOrderQuantity((q) => Math.max(1, q - 1))}
                        className="inline-flex h-11 w-11 items-center justify-center rounded-sm bg-surface-muted text-text hover:bg-border disabled:opacity-40"
                      >
                        <IconMinus size={18} stroke={2.2} aria-hidden="true" />
                      </button>
                      <span className="min-w-8 text-center font-mono text-xl font-bold tabular text-text">
                        {safeQty}
                      </span>
                      <button
                        type="button"
                        aria-label="+"
                        disabled={safeQty >= effectiveMaxQty}
                        onClick={() => setOrderQuantity((q) => Math.min(effectiveMaxQty, q + 1))}
                        className="inline-flex h-11 w-11 items-center justify-center rounded-sm bg-ink-900 text-text-inverse hover:bg-ink-700 disabled:bg-surface-muted disabled:text-text-muted"
                      >
                        <IconPlus size={18} stroke={2.2} aria-hidden="true" />
                      </button>
                    </div>
                  </div>

                  <div className="flex items-baseline justify-between border-t border-divider pt-2.5">
                    <span className="text-sm font-bold text-text">
                      {t("operation.priceLines.total")}
                    </span>
                    <span className="font-mono text-xl font-bold tabular text-text-brand">
                      {formatFcfa(totalAmount, i18n.language)}
                    </span>
                  </div>
                </div>
              )}

              {disabledReason && (
                <p className="border-l-4 border-ink-400 bg-surface-muted px-3 py-2.5 text-xs font-medium text-text-secondary">
                  {disabledReason}
                </p>
              )}

              {user && user.role !== "CUSTOMER" && (
                <p className="border-l-4 border-ink-400 bg-surface-muted px-3 py-2.5 text-xs font-medium text-text-secondary">
                  {t("store.customerAccountOnly")}
                </p>
              )}

              <div className="flex flex-col gap-2">
                {!user ? (
                  <Button
                    variant="primary"
                    fullWidth
                    disabled={!depot.can_order || !isOnline || stockForSelectedOp === 0}
                    onClick={() =>
                      navigate("/login", { state: { from: `/depots/${depot.id}` } })
                    }
                  >
                    {t("store.loginToOrder")}
                  </Button>
                ) : (
                  <Button
                    variant="primary"
                    fullWidth
                    disabled={!canSubmitOrder}
                    isLoading={createOrderMutation.isPending}
                    loadingLabel={t("store.reserving")}
                    onClick={() => void handleSubmitOrder()}
                  >
                    {t("store.reserveAction")}
                  </Button>
                )}

                <a
                  href={`tel:${depot.phone}`}
                  className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-md bg-surface-muted px-4 text-sm font-bold text-text hover:bg-border"
                >
                  <IconPhone size={18} stroke={1.75} aria-hidden="true" />
                  <span>
                    {t("store.call")} · {depot.phone}
                  </span>
                </a>
              </div>
            </div>
          );
        })()}
      </BottomSheet>
    </div>
  );
}
