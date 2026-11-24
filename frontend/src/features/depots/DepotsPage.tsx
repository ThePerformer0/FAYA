/**
 * Écran Dépôts — Fusion « Braise sur Sable » (A + B).
 * Bloc supérieur charbon (recherche + filtres pilules) + liste sur fond sable chaud + carte Leaflet paresseuse.
 */

import {
  IconCurrentLocation,
  IconList,
  IconMapPin,
  IconSearch,
  IconX,
} from "@tabler/icons-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatCapacityKg } from "../../design/formatters";
import {
  EmptyState,
  ErrorBanner,
  FilterChip,
} from "../../design/ui";
import { usePublicSettings } from "../settings/usePublicSettings";
import { DepotCard, DepotCardSkeleton } from "./DepotCard";
import {
  useBrands,
  useDepotsSearch,
  type DepotSearchFilters,
  type OperationType,
} from "./useDepots";

const LazyDepotsMap = lazy(() => import("./DepotsMap"));

const COMMON_CAPACITIES = ["6.00", "12.50", "35.00"] as const;
const OPERATIONS: OperationType[] = ["REFILL", "EXCHANGE", "FIRST_ACQUISITION"];

function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState<boolean>(() =>
    typeof window !== "undefined" ? window.matchMedia("(min-width: 64rem)").matches : false,
  );

  useEffect(() => {
    const media = window.matchMedia("(min-width: 64rem)");
    const onChange = (event: MediaQueryListEvent) => setIsDesktop(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  return isDesktop;
}

export function DepotsPage() {
  const { t, i18n } = useTranslation();
  const isDesktop = useIsDesktop();

  const [mobileView, setMobileView] = useState<"list" | "map">("list");

  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedBrandId, setSelectedBrandId] = useState<string | undefined>(undefined);
  const [selectedCapacity, setSelectedCapacity] = useState<string | undefined>(undefined);
  const [selectedOperation, setSelectedOperation] = useState<OperationType | undefined>(undefined);
  const [openNow, setOpenNow] = useState(false);

  const [userCoords, setUserCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [geoStatus, setGeoStatus] = useState<"idle" | "prompt" | "locating" | "denied" | "unsupported">("idle");

  const [selectedDepotId, setSelectedDepotId] = useState<string | null>(null);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setDebouncedQuery(searchInput.trim());
    }, 280);
    return () => window.clearTimeout(handle);
  }, [searchInput]);

  const filters = useMemo<DepotSearchFilters>(
    () => ({
      q: debouncedQuery || undefined,
      brand: selectedBrandId,
      capacityKg: selectedCapacity,
      operation: selectedOperation,
      openNow,
      lat: userCoords?.lat,
      lng: userCoords?.lng,
    }),
    [debouncedQuery, selectedBrandId, selectedCapacity, selectedOperation, openNow, userCoords],
  );

  const { data: settings } = usePublicSettings();
  const { data: brands = [] } = useBrands();
  const {
    data: depotsPage,
    isLoading,
    isFetching,
    error,
    refetch,
  } = useDepotsSearch(filters);

  const depots = useMemo(() => depotsPage?.results ?? [], [depotsPage]);
  const totalCount = depotsPage?.count ?? 0;

  const hasActiveFilters = Boolean(
    debouncedQuery || selectedBrandId || selectedCapacity || selectedOperation || openNow,
  );

  const selectedDepot = useMemo(
    () => depots.find((d) => d.id === selectedDepotId) ?? null,
    [depots, selectedDepotId],
  );

  const resetFilters = () => {
    setSearchInput("");
    setDebouncedQuery("");
    setSelectedBrandId(undefined);
    setSelectedCapacity(undefined);
    setSelectedOperation(undefined);
    setOpenNow(false);
  };

  const requestGeolocation = () => {
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
        setGeoStatus("idle");
      },
      () => {
        setGeoStatus("denied");
      },
      { enableHighAccuracy: false, timeout: 8000, maximumAge: 60_000 },
    );
  };

  const handleGeoButtonClick = () => {
    if (userCoords) {
      setUserCoords(null);
      setGeoStatus("idle");
      return;
    }
    if (geoStatus === "prompt") {
      requestGeolocation();
    } else {
      setGeoStatus("prompt");
    }
  };

  const shouldRenderMap = isDesktop || mobileView === "map";

  return (
    <div className="flex flex-1 flex-col lg:h-[calc(100dvh-3.5rem)] lg:flex-row lg:overflow-hidden">
      {/* Colonne gauche (recherche charbon + liste sur fond sable chaud) */}
      <section
        aria-label={t("search.title")}
        className={`flex flex-col bg-bg lg:w-[26rem] lg:shrink-0 lg:border-r lg:border-card-border lg:overflow-y-auto ${
          !isDesktop && mobileView === "map" ? "hidden" : "flex-1"
        }`}
      >
        {/* Bloc recherche + filtres dans le bandeau charbon unifié (zéro bordure grise) */}
        <div className="sticky top-0 z-10 bg-header-bg px-4 pt-2 pb-3.5 text-text-inverse">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <label htmlFor="depot-search-q" className="sr-only">
                {t("search.label")}
              </label>
              <IconSearch
                size={20}
                stroke={1.75}
                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-inverse-muted"
                aria-hidden="true"
              />
              <input
                id="depot-search-q"
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={t("search.placeholder")}
                className="h-12 w-full rounded-sm bg-header-surface pr-10 pl-10 text-base text-text-inverse placeholder:text-text-inverse-muted focus:bg-ink-700 focus:outline-none"
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput("");
                    setDebouncedQuery("");
                  }}
                  aria-label={t("search.clearSearch")}
                  className="absolute top-1/2 right-1 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-sm text-text-inverse-muted hover:bg-ink-700 hover:text-text-inverse"
                >
                  <IconX size={18} stroke={1.75} aria-hidden="true" />
                </button>
              )}
            </div>

            <button
              type="button"
              onClick={handleGeoButtonClick}
              aria-label={userCoords ? t("geo.clearLocation") : t("geo.useMyLocation")}
              aria-pressed={Boolean(userCoords)}
              className={`touch-target inline-flex h-12 shrink-0 items-center justify-center gap-1.5 rounded-sm px-3 text-sm font-bold transition-colors duration-150 ${
                userCoords
                  ? "bg-action text-on-action"
                  : "bg-header-surface text-text-inverse hover:bg-ink-700"
              }`}
            >
              <IconCurrentLocation size={20} stroke={1.75} aria-hidden="true" />
              <span className="hidden sm:inline">
                {geoStatus === "locating"
                  ? t("geo.locating")
                  : userCoords
                    ? t("geo.located")
                    : t("geo.useMyLocation")}
              </span>
            </button>
          </div>

          {geoStatus === "prompt" && (
            <div className="mt-2.5 border-l-4 border-action bg-header-surface p-3 text-sm text-text-inverse">
              <p className="text-text-inverse/90">{t("geo.rationale")}</p>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={requestGeolocation}
                  className="inline-flex min-h-10 items-center rounded-sm bg-action px-3.5 text-sm font-bold text-on-action hover:bg-action-pressed"
                >
                  {t("geo.useMyLocation")}
                </button>
                <button
                  type="button"
                  onClick={() => setGeoStatus("idle")}
                  className="inline-flex min-h-10 items-center px-2 text-sm font-medium text-text-inverse-muted underline hover:text-text-inverse"
                >
                  {t("errors.close")}
                </button>
              </div>
            </div>
          )}

          {geoStatus === "denied" && (
            <p role="status" className="mt-2 rounded-md bg-header-surface px-3 py-2 text-xs text-text-inverse-muted">
              {t("geo.denied")}
            </p>
          )}

          {geoStatus === "unsupported" && (
            <p role="status" className="mt-2 rounded-md bg-header-surface px-3 py-2 text-xs text-text-inverse-muted">
              {t("geo.unsupported")}
            </p>
          )}

          {/* Pastilles de filtres sombres avec accent rouge Faya */}
          <div
            className="mt-2 flex items-center gap-2 overflow-x-auto pb-0.5"
            role="group"
            aria-label={t("search.title")}
          >
            <FilterChip
              tone="dark"
              label={t("search.openNow")}
              selected={openNow}
              onClick={() => setOpenNow((v) => !v)}
            />

            {OPERATIONS.map((op) => (
              <FilterChip
                key={op}
                tone="dark"
                label={t(`operation.${op}`)}
                selected={selectedOperation === op}
                onClick={() =>
                  setSelectedOperation((current) => (current === op ? undefined : op))
                }
              />
            ))}

            {COMMON_CAPACITIES.map((cap) => (
              <FilterChip
                key={cap}
                tone="dark"
                label={formatCapacityKg(cap, i18n.language)}
                selected={selectedCapacity === cap}
                onClick={() =>
                  setSelectedCapacity((current) => (current === cap ? undefined : cap))
                }
              />
            ))}

            {brands.map((brand) => (
              <FilterChip
                key={brand.id}
                tone="dark"
                label={brand.name}
                selected={selectedBrandId === brand.id}
                onClick={() =>
                  setSelectedBrandId((current) => (current === brand.id ? undefined : brand.id))
                }
              />
            ))}
          </div>
        </div>

        {/* Barre compteur + réinitialisation sur fond sable */}
        <div className="flex items-center justify-between px-4 pt-3 pb-1 text-xs text-text-secondary">
          <span className="font-medium">
            {isLoading ? "…" : t("search.resultsCount", { count: totalCount })}
            {isFetching && !isLoading ? " · …" : ""}
          </span>
          {hasActiveFilters && (
            <button
              type="button"
              onClick={resetFilters}
              className="py-1 font-bold text-text-brand underline"
            >
              {t("search.resetFilters")}
            </button>
          )}
        </div>

        {/* Liste des dépôts */}
        <div className="flex-1 space-y-3 px-4 pt-2 pb-24 lg:pb-6">
          {error ? (
            <ErrorBanner
              title={t("errors.serverTitle")}
              message={error instanceof Error ? error.message : t("errors.serverBody")}
              onRetry={() => void refetch()}
            />
          ) : isLoading ? (
            <>
              <DepotCardSkeleton />
              <DepotCardSkeleton />
              <DepotCardSkeleton />
            </>
          ) : depots.length === 0 ? (
            <EmptyState
              title={t("search.emptyTitle")}
              body={t("search.emptyBody")}
              actionLabel={hasActiveFilters ? t("search.resetFilters") : undefined}
              onAction={hasActiveFilters ? resetFilters : undefined}
            />
          ) : (
            depots.map((depot) => (
              <DepotCard
                key={depot.id}
                depot={depot}
                serverNow={settings?.server_now}
                selected={isDesktop && selectedDepotId === depot.id}
                activeBrandId={selectedBrandId}
                activeCapacityKg={selectedCapacity}
                onHighlight={isDesktop ? setSelectedDepotId : undefined}
              />
            ))
          )}
        </div>
      </section>

      {/* Carte Leaflet */}
      {shouldRenderMap && (
        <section
          aria-label={t("search.viewMap")}
          className={`relative flex-1 ${
            isDesktop ? "h-full" : "h-[calc(100dvh-7.5rem)] w-full"
          }`}
        >
          <Suspense
            fallback={
              <div className="flex h-full w-full items-center justify-center bg-surface-muted p-6">
                <div className="h-10 w-40 rounded-md bg-ink-200 animate-skeleton" />
              </div>
            }
          >
            <LazyDepotsMap
              depots={depots}
              selectedDepotId={selectedDepotId}
              onSelectDepot={setSelectedDepotId}
              userCoords={userCoords}
            />
          </Suspense>

          {!isDesktop && selectedDepot && (
            <div className="absolute right-3 bottom-20 left-3 z-[400] shadow-sheet">
              <DepotCard
                depot={selectedDepot}
                serverNow={settings?.server_now}
                selected
                activeBrandId={selectedBrandId}
                activeCapacityKg={selectedCapacity}
                compact
              />
            </div>
          )}
        </section>
      )}

      {/* Bouton flottant mobile Carte / Liste */}
      {!isDesktop && (
        <div className="pointer-events-none fixed right-0 bottom-[calc(4.25rem+var(--safe-bottom))] left-0 z-[450] flex justify-center">
          <button
            type="button"
            onClick={() => {
              setSelectedDepotId(null);
              setMobileView((v) => (v === "list" ? "map" : "list"));
            }}
            className="pointer-events-auto inline-flex h-12 items-center gap-2 rounded-full bg-header-bg px-5 font-sans text-base font-bold text-text-inverse shadow-popover"
          >
            {mobileView === "list" ? (
              <>
                <IconMapPin size={20} stroke={1.75} aria-hidden="true" />
                <span>{t("search.viewMap")}</span>
              </>
            ) : (
              <>
                <IconList size={20} stroke={1.75} aria-hidden="true" />
                <span>{t("search.viewList")}</span>
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}
