/**
 * Gestion des stocks par catégorie et historique immuable des mouvements (/depot/stocks).
 * Thème « Braise sur Sable » : zéro bordure 1px grise, surfaces franches + barres d'accent 4 px.
 */

import {
  IconAdjustmentsHorizontal,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconPlus,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../../api/client";
import {
  formatCapacityKg,
  formatIsoTimeInPlatformTz,
  formatShortDate,
} from "../../design/formatters";
import {
  BottomSheet,
  Button,
  EmptyState,
  ErrorBanner,
  FilterChip,
  TextField,
} from "../../design/ui";
import { useNetworkStatus } from "../../shared/NetworkContext";
import { usePortalDepot } from "./PortalShell";
import {
  useAdjustStock,
  useCatalogProducts,
  useManagedStockMovements,
  useManagedStocks,
  useRestockStock,
  useScrapStock,
  type DepotStock,
  type StockAdjustMovementType,
  type StockCategory,
  type StockMovementType,
} from "./useDepotPortal";

const ALL_CATEGORIES: StockCategory[] = ["FULL", "NEW", "EMPTY", "DEPOSIT"];
const MOVEMENT_FILTER_TYPES: StockMovementType[] = [
  "RESTOCK",
  "INVENTORY_CORRECTION",
  "MANUAL_ADJUSTMENT",
  "SCRAP",
  "RESERVATION",
  "RELEASE",
  "PICKUP_OUT",
  "EMPTY_RETURN",
];

function categoryPillClass(category: StockCategory): string {
  if (category === "FULL") return "bg-ink-900 text-text-inverse";
  if (category === "NEW") return "bg-price-band text-text";
  if (category === "EMPTY") return "bg-surface-muted text-text-secondary";
  return "bg-soon-bg text-soon";
}

function stockAccentClass(stock: DepotStock): string {
  if (stock.category === "EMPTY") return "border-ink-400";
  if (stock.available_quantity === 0) return "border-action";
  return "border-ink-900";
}

export function PortalStocksPage() {
  const { t, i18n } = useTranslation();
  const { isOnline } = useNetworkStatus();
  const depot = usePortalDepot();
  const canMutate = depot.is_editable && isOnline;

  const [subView, setSubView] = useState<"levels" | "movements">("levels");
  const [categoryFilter, setCategoryFilter] = useState<StockCategory | undefined>(undefined);
  const [movementTypeFilter, setMovementTypeFilter] = useState<StockMovementType | undefined>(
    undefined,
  );
  const [movementPage, setMovementPage] = useState(1);
  const [flashMessage, setFlashMessage] = useState<string | null>(null);

  const stocksQuery = useManagedStocks({ category: categoryFilter });
  const movementsQuery = useManagedStockMovements({
    category: categoryFilter,
    movementType: movementTypeFilter,
    page: movementPage,
  });
  const catalogQuery = useCatalogProducts();

  const restockMutation = useRestockStock();
  const adjustMutation = useAdjustStock();
  const scrapMutation = useScrapStock();

  // État modale Approvisionnement
  const [restockOpen, setRestockOpen] = useState(false);
  const [restockProductId, setRestockProductId] = useState("");
  const [restockCategory, setRestockCategory] = useState<StockCategory>("FULL");
  const [restockQty, setRestockQty] = useState("10");
  const [restockReason, setRestockReason] = useState("");
  const [restockError, setRestockError] = useState<string | null>(null);

  // État modale Ajustement / Inventaire
  const [adjustStock, setAdjustStock] = useState<DepotStock | null>(null);
  const [adjustNewQty, setAdjustNewQty] = useState("");
  const [adjustType, setAdjustType] = useState<StockAdjustMovementType>("INVENTORY_CORRECTION");
  const [adjustReason, setAdjustReason] = useState("");
  const [adjustError, setAdjustError] = useState<string | null>(null);
  const [adjustConflictCurrent, setAdjustConflictCurrent] = useState<number | null>(null);

  // État modale Mise au rebut
  const [scrapStock, setScrapStock] = useState<DepotStock | null>(null);
  const [scrapQty, setScrapQty] = useState("1");
  const [scrapReason, setScrapReason] = useState("");
  const [scrapError, setScrapError] = useState<string | null>(null);

  const openRestockSheet = (prefill?: DepotStock) => {
    setRestockError(null);
    setRestockProductId(prefill?.product.id ?? catalogQuery.data?.[0]?.id ?? "");
    setRestockCategory(prefill?.category ?? "FULL");
    setRestockQty("10");
    setRestockReason("");
    setRestockOpen(true);
  };

  const openAdjustSheet = (stock: DepotStock) => {
    setAdjustError(null);
    setAdjustConflictCurrent(null);
    setAdjustStock(stock);
    setAdjustNewQty(String(stock.physical_quantity));
    setAdjustType("INVENTORY_CORRECTION");
    setAdjustReason("");
  };

  const openScrapSheet = (stock: DepotStock) => {
    setScrapError(null);
    setScrapStock(stock);
    setScrapQty("1");
    setScrapReason("");
  };

  const handleRestockSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setRestockError(null);
    const qty = Number.parseInt(restockQty, 10);
    if (!restockProductId || Number.isNaN(qty) || qty < 1) {
      setRestockError(t("depotPortal.stocks.fields.quantity"));
      return;
    }
    try {
      await restockMutation.mutateAsync({
        product_id: restockProductId,
        category: restockCategory,
        quantity: qty,
        reason: restockReason.trim(),
      });
      setRestockOpen(false);
      setFlashMessage(t("depotPortal.stocks.savedRestock"));
    } catch (err) {
      setRestockError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const handleAdjustSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!adjustStock) return;
    setAdjustError(null);
    setAdjustConflictCurrent(null);
    const newQty = Number.parseInt(adjustNewQty, 10);
    if (Number.isNaN(newQty) || newQty < 0) {
      setAdjustError(t("depotPortal.stocks.fields.newPhysicalQuantity"));
      return;
    }
    try {
      await adjustMutation.mutateAsync({
        product_id: adjustStock.product.id,
        category: adjustStock.category,
        new_physical_quantity: newQty,
        movement_type: adjustType,
        reason: adjustReason.trim(),
        expected_physical_quantity: adjustStock.physical_quantity,
      });
      setAdjustStock(null);
      setFlashMessage(t("depotPortal.stocks.savedAdjust"));
    } catch (err) {
      if (err instanceof ApiError && err.code === "STOCK_CONFLICT") {
        const currentVal = err.details?.current_physical_quantity;
        if (typeof currentVal === "number") {
          setAdjustConflictCurrent(currentVal);
        }
      }
      setAdjustError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const handleScrapSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!scrapStock) return;
    setScrapError(null);
    const qty = Number.parseInt(scrapQty, 10);
    if (Number.isNaN(qty) || qty < 1) {
      setScrapError(t("depotPortal.stocks.fields.scrapQuantity"));
      return;
    }
    try {
      await scrapMutation.mutateAsync({
        product_id: scrapStock.product.id,
        category: scrapStock.category,
        quantity: qty,
        reason: scrapReason.trim(),
      });
      setScrapStock(null);
      setFlashMessage(t("depotPortal.stocks.savedScrap"));
    } catch (err) {
      setScrapError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const stocks = stocksQuery.data?.results ?? [];
  const movements = movementsQuery.data?.results ?? [];
  const movementCount = movementsQuery.data?.count ?? 0;

  return (
    <div className="space-y-4">
      {/* Barre supérieure : bascule Niveaux / Historique + CTA Approvisionner */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-sm bg-surface-muted p-1">
          <button
            type="button"
            onClick={() => setSubView("levels")}
            className={`min-h-10 rounded-sm px-3.5 text-sm font-bold transition-colors duration-150 ${
              subView === "levels"
                ? "bg-ink-900 text-text-inverse"
                : "text-text-secondary hover:text-text"
            }`}
          >
            {t("depotPortal.stocks.subviewLevels")}
          </button>
          <button
            type="button"
            onClick={() => setSubView("movements")}
            className={`min-h-10 rounded-sm px-3.5 text-sm font-bold transition-colors duration-150 ${
              subView === "movements"
                ? "bg-ink-900 text-text-inverse"
                : "text-text-secondary hover:text-text"
            }`}
          >
            {t("depotPortal.stocks.subviewMovements")}
          </button>
        </div>

        <Button
          variant="primary"
          disabled={!canMutate}
          onClick={() => openRestockSheet()}
          className="min-h-11 px-4 text-base"
        >
          <IconPlus size={18} stroke={2.2} aria-hidden="true" />
          <span>{t("depotPortal.stocks.restockAction")}</span>
        </Button>
      </div>

      {flashMessage && (
        <div
          role="status"
          className="flex items-center justify-between gap-2 border-l-4 border-open bg-open-bg px-3.5 py-2.5 text-sm font-bold text-open"
        >
          <span className="inline-flex items-center gap-2">
            <IconCheck size={18} stroke={2.2} aria-hidden="true" />
            {flashMessage}
          </span>
          <button
            type="button"
            onClick={() => setFlashMessage(null)}
            className="text-xs underline"
          >
            {t("errors.close")}
          </button>
        </div>
      )}

      {/* Filtres par catégorie */}
      <div className="flex flex-wrap items-center gap-1.5">
        <FilterChip
          label={t("depotPortal.stocks.allCategories")}
          selected={categoryFilter === undefined}
          onClick={() => {
            setCategoryFilter(undefined);
            setMovementPage(1);
          }}
        />
        {ALL_CATEGORIES.map((cat) => (
          <FilterChip
            key={cat}
            label={t(`depotPortal.stocks.categories.${cat}`)}
            selected={categoryFilter === cat}
            onClick={() => {
              setCategoryFilter(categoryFilter === cat ? undefined : cat);
              setMovementPage(1);
            }}
          />
        ))}
      </div>

      {/* VUE NIVEAUX DE STOCK */}
      {subView === "levels" && (
        <>
          {stocksQuery.isLoading ? (
            <div className="space-y-3">
              <div className="h-32 w-full bg-card animate-skeleton" />
              <div className="h-32 w-full bg-card animate-skeleton" />
            </div>
          ) : stocksQuery.error ? (
            <ErrorBanner
              title={t("errors.serverTitle")}
              message={
                stocksQuery.error instanceof Error
                  ? stocksQuery.error.message
                  : t("errors.serverBody")
              }
              onRetry={() => void stocksQuery.refetch()}
            />
          ) : stocks.length === 0 ? (
            <EmptyState
              title={t("depotPortal.stocks.emptyTitle")}
              body={t("depotPortal.stocks.emptyBody")}
              actionLabel={canMutate ? t("depotPortal.stocks.restockAction") : undefined}
              onAction={canMutate ? () => openRestockSheet() : undefined}
            />
          ) : (
            <div className="space-y-3">
              {stocks.map((stock) => {
                const isEmpty = stock.category === "EMPTY";
                const canScrap = canMutate && stock.physical_quantity - stock.reserved_quantity > 0;
                return (
                  <article
                    key={stock.id}
                    className={`overflow-hidden rounded-r-sm border-l-4 bg-card ${stockAccentClass(
                      stock,
                    )}`}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5 pb-2.5">
                      <div className="min-w-0">
                        <h2 className="font-display text-xl font-bold uppercase tracking-[0.4px] text-text">
                          {stock.product.brand.name} ·{" "}
                          {formatCapacityKg(stock.product.capacity_kg, i18n.language)}
                        </h2>
                        <p className="text-xs text-text-secondary">{stock.product.name}</p>
                      </div>
                      <span
                        className={`inline-flex min-h-6 items-center rounded-sm px-2.5 py-0.5 text-xs font-bold ${categoryPillClass(
                          stock.category,
                        )}`}
                      >
                        {t(`depotPortal.stocks.categories.${stock.category}`)}
                      </span>
                    </div>

                    {/* Bande chiffres Physique / Réservé / Disponible */}
                    <dl className="grid grid-cols-3 gap-2 bg-price-band px-4 py-2.5">
                      <div>
                        <dt className="text-[11px] font-bold uppercase tracking-[0.4px] text-text-secondary">
                          {t("depotPortal.stocks.physical")}
                        </dt>
                        <dd className="mt-0.5 font-mono text-xl font-medium tabular text-text">
                          {stock.physical_quantity}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[11px] font-bold uppercase tracking-[0.4px] text-text-secondary">
                          {t("depotPortal.stocks.reserved")}
                        </dt>
                        <dd className="mt-0.5 font-mono text-xl font-medium tabular text-text-secondary">
                          {stock.reserved_quantity}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-[11px] font-bold uppercase tracking-[0.4px] text-text-secondary">
                          {t("depotPortal.stocks.available")}
                        </dt>
                        <dd
                          className={`mt-0.5 font-mono text-xl font-medium tabular ${
                            isEmpty
                              ? "text-text-muted"
                              : stock.available_quantity > 0
                                ? "text-text-brand"
                                : "text-soon"
                          }`}
                        >
                          {isEmpty ? (
                            <span className="font-sans text-xs font-bold uppercase">
                              {t("depotPortal.stocks.notSellable")}
                            </span>
                          ) : (
                            stock.available_quantity
                          )}
                        </dd>
                      </div>
                    </dl>

                    {/* Actions directes sur la ligne de stock */}
                    <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
                      <button
                        type="button"
                        disabled={!canMutate}
                        onClick={() => openRestockSheet(stock)}
                        className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-ink-900 px-3 text-xs font-bold uppercase tracking-[0.3px] text-text-inverse hover:bg-ink-700 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
                      >
                        <IconPlus size={15} stroke={2.2} aria-hidden="true" />
                        <span>{t("depotPortal.stocks.restockAction")}</span>
                      </button>

                      <button
                        type="button"
                        disabled={!canMutate}
                        onClick={() => openAdjustSheet(stock)}
                        className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-surface-muted px-3 text-xs font-bold uppercase tracking-[0.3px] text-text hover:bg-border disabled:cursor-not-allowed disabled:text-text-muted"
                      >
                        <IconAdjustmentsHorizontal size={15} stroke={2} aria-hidden="true" />
                        <span>{t("depotPortal.stocks.adjustAction")}</span>
                      </button>

                      <button
                        type="button"
                        disabled={!canScrap}
                        onClick={() => openScrapSheet(stock)}
                        className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-danger-bg px-3 text-xs font-bold uppercase tracking-[0.3px] text-danger hover:bg-danger hover:text-on-action disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
                      >
                        <IconTrash size={15} stroke={2} aria-hidden="true" />
                        <span>{t("depotPortal.stocks.scrapAction")}</span>
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </>
      )}

      {/* VUE HISTORIQUE IMMUABLE DES MOUVEMENTS */}
      {subView === "movements" && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <FilterChip
              label={t("depotPortal.stocks.allTypes")}
              selected={movementTypeFilter === undefined}
              onClick={() => {
                setMovementTypeFilter(undefined);
                setMovementPage(1);
              }}
            />
            {MOVEMENT_FILTER_TYPES.map((mt) => (
              <FilterChip
                key={mt}
                label={t(`depotPortal.stocks.movementTypes.${mt}`)}
                selected={movementTypeFilter === mt}
                onClick={() => {
                  setMovementTypeFilter(movementTypeFilter === mt ? undefined : mt);
                  setMovementPage(1);
                }}
              />
            ))}
          </div>

          {movementsQuery.isLoading ? (
            <div className="space-y-2">
              <div className="h-20 w-full bg-card animate-skeleton" />
              <div className="h-20 w-full bg-card animate-skeleton" />
            </div>
          ) : movementsQuery.error ? (
            <ErrorBanner
              title={t("errors.serverTitle")}
              message={
                movementsQuery.error instanceof Error
                  ? movementsQuery.error.message
                  : t("errors.serverBody")
              }
              onRetry={() => void movementsQuery.refetch()}
            />
          ) : movements.length === 0 ? (
            <EmptyState
              title={t("depotPortal.stocks.emptyMovementsTitle")}
              body={t("depotPortal.stocks.emptyMovementsBody")}
            />
          ) : (
            <>
              <ul className="divide-y divide-divider border-l-4 border-ink-900 bg-card">
                {movements.map((mv) => {
                  const isPositive = mv.delta > 0;
                  const deltaText = isPositive ? `+${mv.delta}` : String(mv.delta);
                  return (
                    <li key={mv.id} className="px-4 py-3.5">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-sans text-sm font-bold text-text">
                              {mv.product.brand.name} ·{" "}
                              {formatCapacityKg(mv.product.capacity_kg, i18n.language)}
                            </span>
                            <span
                              className={`inline-flex rounded-sm px-2 py-0.5 text-[11px] font-bold ${categoryPillClass(
                                mv.category,
                              )}`}
                            >
                              {t(`depotPortal.stocks.categories.${mv.category}`)}
                            </span>
                            <span className="rounded-sm bg-price-band px-2 py-0.5 text-[11px] font-bold text-text-secondary">
                              {t(`depotPortal.stocks.movementTypes.${mv.movement_type}`)}
                            </span>
                          </div>
                          {mv.reason && (
                            <p className="mt-1 text-sm text-text-secondary">{mv.reason}</p>
                          )}
                          <p className="mt-1 text-xs text-text-muted">
                            {formatShortDate(mv.created_at, i18n.language)} ·{" "}
                            {formatIsoTimeInPlatformTz(mv.created_at)} ·{" "}
                            {mv.actor_name ?? t("depotPortal.stocks.systemActor")}
                          </p>
                        </div>

                        <div className="shrink-0 text-right">
                          <p
                            className={`font-mono text-lg font-bold tabular ${
                              isPositive ? "text-open" : "text-danger"
                            }`}
                          >
                            {deltaText}
                          </p>
                          <p className="font-mono text-xs tabular text-text-secondary">
                            {mv.quantity_before} → {mv.quantity_after}
                          </p>
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>

              {(movementsQuery.data?.previous || movementsQuery.data?.next) && (
                <div className="flex items-center justify-between gap-2 pt-2">
                  <Button
                    variant="secondary"
                    disabled={!movementsQuery.data?.previous}
                    onClick={() => setMovementPage((p) => Math.max(1, p - 1))}
                  >
                    <IconChevronLeft size={18} stroke={2} aria-hidden="true" />
                    <span>{t("depotPortal.stocks.previousPage")}</span>
                  </Button>
                  <span className="font-mono text-xs tabular text-text-secondary">
                    {t("depotPortal.stocks.pageStatus", {
                      page: movementPage,
                      count: movementCount,
                    })}
                  </span>
                  <Button
                    variant="secondary"
                    disabled={!movementsQuery.data?.next}
                    onClick={() => setMovementPage((p) => p + 1)}
                  >
                    <span>{t("depotPortal.stocks.nextPage")}</span>
                    <IconChevronRight size={18} stroke={2} aria-hidden="true" />
                  </Button>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* MODALE APPROVISIONNEMENT */}
      <BottomSheet
        open={restockOpen}
        title={t("depotPortal.stocks.restockTitle")}
        onClose={() => setRestockOpen(false)}
      >
        <form onSubmit={(e) => void handleRestockSubmit(e)} className="space-y-4">
          {restockError && <ErrorBanner message={restockError} />}

          <div className="space-y-1.5">
            <label
              htmlFor="restock-product"
              className="block text-sm font-bold uppercase tracking-[0.3px] text-text-secondary"
            >
              {t("depotPortal.stocks.fields.product")}
            </label>
            <select
              id="restock-product"
              value={restockProductId}
              onChange={(e) => setRestockProductId(e.target.value)}
              required
              className="h-12 w-full rounded-t-sm border-b-2 border-ink-900/20 bg-card px-3.5 text-base text-text focus:border-action focus:outline-none"
            >
              <option value="">{t("depotPortal.stocks.fields.selectProduct")}</option>
              {(catalogQuery.data ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.brand.name} · {formatCapacityKg(p.capacity_kg, i18n.language)} ({p.name})
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="restock-category"
              className="block text-sm font-bold uppercase tracking-[0.3px] text-text-secondary"
            >
              {t("depotPortal.stocks.fields.category")}
            </label>
            <select
              id="restock-category"
              value={restockCategory}
              onChange={(e) => setRestockCategory(e.target.value as StockCategory)}
              className="h-12 w-full rounded-t-sm border-b-2 border-ink-900/20 bg-card px-3.5 text-base text-text focus:border-action focus:outline-none"
            >
              {ALL_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>
                  {t(`depotPortal.stocks.categories.${cat}`)}
                </option>
              ))}
            </select>
          </div>

          <TextField
            id="restock-qty"
            type="number"
            min={1}
            step={1}
            required
            label={t("depotPortal.stocks.fields.quantity")}
            value={restockQty}
            onChange={(e) => setRestockQty(e.target.value)}
          />

          <TextField
            id="restock-reason"
            label={t("depotPortal.stocks.fields.reasonOptional")}
            placeholder={t("depotPortal.stocks.fields.reasonPlaceholderRestock")}
            maxLength={500}
            value={restockReason}
            onChange={(e) => setRestockReason(e.target.value)}
          />

          <Button
            type="submit"
            variant="primary"
            fullWidth
            isLoading={restockMutation.isPending}
            loadingLabel={t("auth.saving")}
          >
            {t("depotPortal.stocks.restockAction")}
          </Button>
        </form>
      </BottomSheet>

      {/* MODALE CORRECTION / INVENTAIRE */}
      <BottomSheet
        open={Boolean(adjustStock)}
        title={t("depotPortal.stocks.adjustTitle")}
        onClose={() => setAdjustStock(null)}
      >
        {adjustStock && (
          <form onSubmit={(e) => void handleAdjustSubmit(e)} className="space-y-4">
            <div className="border-l-4 border-ink-900 bg-card px-3.5 py-2.5">
              <p className="font-bold text-text">
                {adjustStock.product.brand.name} ·{" "}
                {formatCapacityKg(adjustStock.product.capacity_kg, i18n.language)} ·{" "}
                {t(`depotPortal.stocks.categories.${adjustStock.category}`)}
              </p>
              <p className="mt-0.5 font-mono text-xs tabular text-text-secondary">
                {t("depotPortal.stocks.currentSummary", {
                  physical: adjustStock.physical_quantity,
                  reserved: adjustStock.reserved_quantity,
                })}
              </p>
            </div>

            {adjustError && (
              <div className="space-y-2">
                <ErrorBanner message={adjustError} />
                {adjustConflictCurrent !== null && (
                  <Button
                    variant="secondary"
                    fullWidth
                    onClick={() => {
                      void stocksQuery.refetch();
                      setAdjustStock(null);
                    }}
                  >
                    <IconRefresh size={18} stroke={2} aria-hidden="true" />
                    <span>{t("depotPortal.stocks.conflictReload")}</span>
                  </Button>
                )}
              </div>
            )}

            <div className="space-y-1.5">
              <label
                htmlFor="adjust-type"
                className="block text-sm font-bold uppercase tracking-[0.3px] text-text-secondary"
              >
                {t("depotPortal.stocks.fields.movementType")}
              </label>
              <select
                id="adjust-type"
                value={adjustType}
                onChange={(e) => setAdjustType(e.target.value as StockAdjustMovementType)}
                className="h-12 w-full rounded-t-sm border-b-2 border-ink-900/20 bg-card px-3.5 text-base text-text focus:border-action focus:outline-none"
              >
                <option value="INVENTORY_CORRECTION">
                  {t("depotPortal.stocks.movementTypes.INVENTORY_CORRECTION")}
                </option>
                <option value="MANUAL_ADJUSTMENT">
                  {t("depotPortal.stocks.movementTypes.MANUAL_ADJUSTMENT")}
                </option>
              </select>
            </div>

            <TextField
              id="adjust-new-qty"
              type="number"
              min={adjustStock.reserved_quantity}
              step={1}
              required
              label={t("depotPortal.stocks.fields.newPhysicalQuantity")}
              value={adjustNewQty}
              onChange={(e) => setAdjustNewQty(e.target.value)}
            />

            <TextField
              id="adjust-reason"
              required
              maxLength={500}
              label={t("depotPortal.stocks.fields.reasonRequired")}
              placeholder={t("depotPortal.stocks.fields.reasonPlaceholderAdjust")}
              value={adjustReason}
              onChange={(e) => setAdjustReason(e.target.value)}
            />

            <Button
              type="submit"
              variant="primary"
              fullWidth
              isLoading={adjustMutation.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("auth.saveAction")}
            </Button>
          </form>
        )}
      </BottomSheet>

      {/* MODALE MISE AU REBUT */}
      <BottomSheet
        open={Boolean(scrapStock)}
        title={t("depotPortal.stocks.scrapTitle")}
        onClose={() => setScrapStock(null)}
      >
        {scrapStock && (
          <form onSubmit={(e) => void handleScrapSubmit(e)} className="space-y-4">
            <div className="border-l-4 border-danger bg-card px-3.5 py-2.5">
              <p className="font-bold text-text">
                {scrapStock.product.brand.name} ·{" "}
                {formatCapacityKg(scrapStock.product.capacity_kg, i18n.language)} ·{" "}
                {t(`depotPortal.stocks.categories.${scrapStock.category}`)}
              </p>
              <p className="mt-0.5 font-mono text-xs tabular text-text-secondary">
                {t("depotPortal.stocks.currentSummary", {
                  physical: scrapStock.physical_quantity,
                  reserved: scrapStock.reserved_quantity,
                })}
              </p>
            </div>

            {scrapError && <ErrorBanner message={scrapError} />}

            <TextField
              id="scrap-qty"
              type="number"
              min={1}
              max={Math.max(1, scrapStock.physical_quantity - scrapStock.reserved_quantity)}
              step={1}
              required
              label={t("depotPortal.stocks.fields.scrapQuantity")}
              value={scrapQty}
              onChange={(e) => setScrapQty(e.target.value)}
            />

            <TextField
              id="scrap-reason"
              required
              maxLength={500}
              label={t("depotPortal.stocks.fields.reasonRequired")}
              placeholder={t("depotPortal.stocks.fields.reasonPlaceholderScrap")}
              value={scrapReason}
              onChange={(e) => setScrapReason(e.target.value)}
            />

            <Button
              type="submit"
              variant="danger"
              fullWidth
              isLoading={scrapMutation.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("depotPortal.stocks.scrapAction")}
            </Button>
          </form>
        )}
      </BottomSheet>
    </div>
  );
}
