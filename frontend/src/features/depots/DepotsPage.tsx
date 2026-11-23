/**
 * Écran Dépôts : recherche, filtres, liste par défaut sur mobile, split-view desktop (DESIGN_SYSTEM §3.5).
 * Leaflet n'est chargé dynamiquement qu'à l'ouverture de la carte ou sur desktop (≥ 64 rem).
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
  Button,
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

  // Vue mobile : liste par défaut (DESIGN_SYSTEM §3.5)
  const [mobileView, setMobileView] = useState<"list" | "map">("list");

  // Filtres de recherche
  const [searchInput, setSearchInput] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedBrandId, setSelectedBrandId] = useState<string | undefined>(undefined);
  const [selectedCapacity, setSelectedCapacity] = useState<string | undefined>(undefined);
  const [selectedOperation, setSelectedOperation] = useState<OperationType | undefined>(undefined);
  const [openNow, setOpenNow] = useState(false);

  // Géolocalisation optionnelle avec explication préalable (DESIGN_SYSTEM §5.2)
  const [userCoords, setUserCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [geoStatus, setGeoStatus] = useState<"idle" | "prompt" | "locating" | "denied" | "unsupported">("idle");

  // Sélection bidirectionnelle liste <-> carte
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
      {/* Colonne gauche (liste + recherche + filtres) */}
      <section
        aria-label={t("search.title")}
        className={`flex flex-col bg-bg lg:w-[25rem] lg:shrink-0 lg:border-r lg:border-divider lg:overflow-y-auto ${
          !isDesktop && mobileView === "map" ? "hidden" : "flex-1"
        }`}
      >
        {/* Zone recherche + localisation + filtres */}
        <div className="sticky top-0 z-10 border-b border-divider bg-bg px-4 pt-3 pb-2">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <label htmlFor="depot-search-q" className="sr-only">
                {t("search.label")}
              </label>
              <IconSearch
                size={20}
                stroke={1.75}
                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-text-secondary"
                aria-hidden="true"
              />
              <input
                id="depot-search-q"
                type="search"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                placeholder={t("search.placeholder")}
                className="h-12 w-full rounded-md border-card border-ink-600 bg-white pr-10 pl-10 text-base text-text placeholder:text-text-muted focus:border-border-strong focus:outline-none"
              />
              {searchInput && (
                <button
                  type="button"
                  onClick={() => {
                    setSearchInput("");
                    setDebouncedQuery("");
                  }}
                  aria-label={t("search.clearSearch")}
                  className="absolute top-1/2 right-1 inline-flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-md text-text-secondary hover:bg-surface-muted"
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
              className={`touch-target inline-flex h-12 shrink-0 items-center justify-center gap-1.5 rounded-md border-card px-3 text-sm font-bold transition-colors duration-150 ${
                userCoords
                  ? "border-border-strong bg-ink-900 text-text-inverse"
                  : "border-border-strong bg-bg text-text hover:bg-surface-muted"
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

          {/* Explication avant demande GPS (DESIGN_SYSTEM §5.2) */}
          {geoStatus === "prompt" && (
            <div className="mt-2 rounded-md border-card border-border-strong bg-surface-muted p-3 text-sm text-text">
              <p>{t("geo.rationale")}</p>
              <div className="mt-2.5 flex flex-wrap gap-2">
                <Button variant="secondary" onClick={requestGeolocation}>
                  {t("geo.useMyLocation")}
                </Button>
                <Button variant="link" onClick={() => setGeoStatus("idle")}>
                  {t("errors.close")}
                </Button>
              </div>
            </div>
          )}

          {geoStatus === "denied" && (
            <p role="status" className="mt-2 rounded-md bg-surface-muted px-3 py-2 text-sm text-text-secondary">
              {t("geo.denied")}
            </p>
          )}

          {geoStatus === "unsupported" && (
            <p role="status" className="mt-2 rounded-md bg-surface-muted px-3 py-2 text-sm text-text-secondary">
              {t("geo.unsupported")}
            </p>
          )}

          {/* Pastilles de filtres défilantes */}
          <div
            className="mt-2 flex items-center gap-2 overflow-x-auto pb-1"
            role="group"
            aria-label={t("search.title")}
          >
            <FilterChip
              label={t("search.openNow")}
              selected={openNow}
              onClick={() => setOpenNow((v) => !v)}
            />

            {OPERATIONS.map((op) => (
              <FilterChip
                key={op}
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
                label={brand.name}
                selected={selectedBrandId === brand.id}
                onClick={() =>
                  setSelectedBrandId((current) => (current === brand.id ? undefined : brand.id))
                }
              />
            ))}
          </div>

          {/* Compteur + réinitialisation */}
          <div className="mt-1 flex items-center justify-between text-xs text-text-secondary">
            <span>
              {isLoading ? "…" : t("search.resultsCount", { count: totalCount })}
              {isFetching && !isLoading ? " · …" : ""}
            </span>
            {hasActiveFilters && (
              <button
                type="button"
                onClick={resetFilters}
                className="font-bold text-text-brand underline py-1"
              >
                {t("search.resetFilters")}
              </button>
            )}
          </div>
        </div>

        {/* Liste des dépôts */}
        <div className="flex-1 space-y-3 px-4 pt-3 pb-24 lg:pb-6">
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

      {/* Panneau carte (chargé uniquement si desktop ou clic sur « Carte » sur mobile) */}
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

          {/* Carte aperçu compacte en bas sur mobile quand un repère est sélectionné (DESIGN_SYSTEM §3.5) */}
          {!isDesktop && selectedDepot && (
            <div className="absolute right-3 bottom-20 left-3 z-[400] shadow-sheet rounded-lg">
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

      {/* Bouton flottant mobile « Carte » / « Liste » (hauteur 48 px, centré, DESIGN_SYSTEM §3.5) */}
      {!isDesktop && (
        <div className="pointer-events-none fixed right-0 bottom-[calc(4.25rem+env(safe-area-inset-bottom))] left-0 z-[450] flex justify-center">
          <button
            type="button"
            onClick={() => {
              setSelectedDepotId(null);
              setMobileView((v) => (v === "list" ? "map" : "list"));
            }}
            className="pointer-events-auto inline-flex h-12 items-center gap-2 rounded-full border-card border-border-strong bg-ink-900 px-5 font-sans text-base font-bold text-text-inverse shadow-popover"
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
