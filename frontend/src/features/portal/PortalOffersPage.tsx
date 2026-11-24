/**
 * Gestion des offres commerciales, prix par opération, marques d'échange et propositions catalogue
 * (/depot/offers). Thème « Braise sur Sable » : zéro bordure 1px grise.
 */

import {
  IconCheck,
  IconEdit,
  IconEye,
  IconEyeOff,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { formatCapacityKg, formatFcfa } from "../../design/formatters";
import {
  BottomSheet,
  Button,
  EmptyState,
  ErrorBanner,
  FilterChip,
  TextField,
} from "../../design/ui";
import { useNetworkStatus } from "../../shared/NetworkContext";
import { useBrands, type OperationType } from "../depots/useDepots";
import { usePortalDepot } from "./PortalShell";
import {
  useCatalogProducts,
  useCreateManagedOffer,
  useCreateManagedProposal,
  useDeleteManagedOffer,
  useManagedOffers,
  useManagedProposals,
  useUpdateManagedOffer,
  type ManagedOffer,
  type ManagedOfferOperationInput,
  type ManagedProductProposal,
} from "./useDepotPortal";

interface OpDraft {
  enabled: boolean;
  gasPrice: string;
  bottlePrice: string;
  depositAmount: string;
}

type OpDraftMap = Record<OperationType, OpDraft>;

const OPERATION_ORDER: OperationType[] = ["REFILL", "EXCHANGE", "FIRST_ACQUISITION"];

function emptyOpsDraft(): OpDraftMap {
  return {
    REFILL: { enabled: true, gasPrice: "6500", bottlePrice: "0", depositAmount: "0" },
    EXCHANGE: { enabled: false, gasPrice: "6500", bottlePrice: "0", depositAmount: "0" },
    FIRST_ACQUISITION: { enabled: false, gasPrice: "6500", bottlePrice: "15000", depositAmount: "0" },
  };
}

function offerToOpsDraft(offer: ManagedOffer): OpDraftMap {
  const draft: OpDraftMap = {
    REFILL: { enabled: false, gasPrice: "6500", bottlePrice: "0", depositAmount: "0" },
    EXCHANGE: { enabled: false, gasPrice: "6500", bottlePrice: "0", depositAmount: "0" },
    FIRST_ACQUISITION: { enabled: false, gasPrice: "6500", bottlePrice: "15000", depositAmount: "0" },
  };
  for (const op of offer.operations) {
    draft[op.operation_type] = {
      enabled: op.is_active,
      gasPrice: String(op.gas_price),
      bottlePrice: String(op.bottle_price),
      depositAmount: String(op.deposit_amount),
    };
  }
  return draft;
}

function proposalStatusClass(status: ManagedProductProposal["status"]): string {
  if (status === "APPROVED") return "bg-open-bg text-open";
  if (status === "REJECTED") return "bg-danger-bg text-danger";
  return "bg-soon-bg text-soon";
}

export function PortalOffersPage() {
  const { t, i18n } = useTranslation();
  const { isOnline } = useNetworkStatus();
  const depot = usePortalDepot();
  const canMutate = depot.is_editable && isOnline;

  const [subView, setSubView] = useState<"offers" | "proposals">("offers");
  const [flashMessage, setFlashMessage] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const offersQuery = useManagedOffers();
  const proposalsQuery = useManagedProposals();
  const productsQuery = useCatalogProducts();
  const brandsQuery = useBrands();

  const createOffer = useCreateManagedOffer();
  const updateOffer = useUpdateManagedOffer();
  const deleteOffer = useDeleteManagedOffer();
  const createProposal = useCreateManagedProposal();

  // Modale Offre (création / édition)
  const [offerModalMode, setOfferModalMode] = useState<"create" | "edit" | null>(null);
  const [editingOffer, setEditingOffer] = useState<ManagedOffer | null>(null);
  const [selectedProductId, setSelectedProductId] = useState("");
  const [offerActive, setOfferActive] = useState(true);
  const [offerNotes, setOfferNotes] = useState("");
  const [opsDraft, setOpsDraft] = useState<OpDraftMap>(emptyOpsDraft);
  const [exchangeBrandIds, setExchangeBrandIds] = useState<string[]>([]);
  const [offerError, setOfferError] = useState<string | null>(null);

  // Modale Proposition produit
  const [proposalOpen, setProposalOpen] = useState(false);
  const [propBrandName, setPropBrandName] = useState("");
  const [propName, setPropName] = useState("");
  const [propCapacity, setPropCapacity] = useState("12.5");
  const [propType, setPropType] = useState<"BUTANE" | "PROPANE" | "LPG">("BUTANE");
  const [propDescription, setPropDescription] = useState("");
  const [proposalError, setProposalError] = useState<string | null>(null);

  const offers = useMemo(() => offersQuery.data?.results ?? [], [offersQuery.data]);
  const proposals = proposalsQuery.data?.results ?? [];
  const allProducts = useMemo(() => productsQuery.data ?? [], [productsQuery.data]);
  const allBrands = brandsQuery.data ?? [];

  const availableProductsForCreate = useMemo(() => {
    const usedIds = new Set(offers.map((o) => o.product.id));
    return allProducts.filter((p) => !usedIds.has(p.id));
  }, [allProducts, offers]);

  const activeProductForModal = useMemo(() => {
    if (offerModalMode === "edit" && editingOffer) return editingOffer.product;
    return allProducts.find((p) => p.id === selectedProductId) ?? null;
  }, [offerModalMode, editingOffer, allProducts, selectedProductId]);

  const selectableExchangeBrands = useMemo(() => {
    const ownBrandId = activeProductForModal?.brand.id;
    return allBrands.filter((b) => b.id !== ownBrandId);
  }, [allBrands, activeProductForModal]);

  const openCreateOfferModal = () => {
    setOfferError(null);
    setEditingOffer(null);
    const firstAvailable = availableProductsForCreate[0]?.id ?? "";
    setSelectedProductId(firstAvailable);
    setOfferActive(true);
    setOfferNotes("");
    setOpsDraft(emptyOpsDraft());
    setExchangeBrandIds([]);
    setOfferModalMode("create");
  };

  const openEditOfferModal = (offer: ManagedOffer) => {
    setOfferError(null);
    setEditingOffer(offer);
    setSelectedProductId(offer.product.id);
    setOfferActive(offer.is_active);
    setOfferNotes(offer.notes);
    setOpsDraft(offerToOpsDraft(offer));
    setExchangeBrandIds(offer.exchange_brands.map((b) => b.id));
    setOfferModalMode("edit");
  };

  const toggleExchangeBrand = (brandId: string) => {
    setExchangeBrandIds((prev) =>
      prev.includes(brandId) ? prev.filter((id) => id !== brandId) : [...prev, brandId],
    );
  };

  const buildOperationsPayload = (): ManagedOfferOperationInput[] => {
    const ops: ManagedOfferOperationInput[] = [];
    for (const opType of OPERATION_ORDER) {
      const entry = opsDraft[opType];
      if (!entry.enabled) continue;
      const gas = Math.max(0, Number.parseInt(entry.gasPrice || "0", 10) || 0);
      if (opType === "FIRST_ACQUISITION") {
        const bottle = Math.max(0, Number.parseInt(entry.bottlePrice || "0", 10) || 0);
        const deposit = Math.max(0, Number.parseInt(entry.depositAmount || "0", 10) || 0);
        ops.push({
          operation_type: opType,
          is_active: true,
          gas_price: gas,
          bottle_price: bottle,
          deposit_amount: deposit,
        });
      } else {
        ops.push({
          operation_type: opType,
          is_active: true,
          gas_price: gas,
          bottle_price: 0,
          deposit_amount: 0,
        });
      }
    }
    return ops;
  };

  const handleSaveOffer = async (event: FormEvent) => {
    event.preventDefault();
    setOfferError(null);
    const operations = buildOperationsPayload();
    const ownBrandId = activeProductForModal?.brand.id;
    const cleanExchangeIds = opsDraft.EXCHANGE.enabled
      ? exchangeBrandIds.filter((id) => id !== ownBrandId)
      : [];

    try {
      if (offerModalMode === "create") {
        if (!selectedProductId) return;
        await createOffer.mutateAsync({
          product_id: selectedProductId,
          is_active: offerActive,
          notes: offerNotes.trim(),
          operations,
          exchange_brand_ids: cleanExchangeIds,
        });
      } else if (offerModalMode === "edit" && editingOffer) {
        await updateOffer.mutateAsync({
          offerId: editingOffer.id,
          body: {
            is_active: offerActive,
            notes: offerNotes.trim(),
            operations,
            exchange_brand_ids: cleanExchangeIds,
          },
        });
      }
      setOfferModalMode(null);
      setFlashMessage(t("depotPortal.offers.saved"));
    } catch (err) {
      setOfferError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const handleToggleOfferActive = async (offer: ManagedOffer) => {
    try {
      await updateOffer.mutateAsync({
        offerId: offer.id,
        body: { is_active: !offer.is_active },
      });
      setFlashMessage(t("depotPortal.offers.saved"));
    } catch {
      // Erreur remontée dans le prochain cycle
    }
  };

  const handleConfirmDelete = async (offerId: string) => {
    try {
      await deleteOffer.mutateAsync(offerId);
      setConfirmDeleteId(null);
      setFlashMessage(t("depotPortal.offers.deleted"));
    } catch {
      setConfirmDeleteId(null);
    }
  };

  const handleCreateProposal = async (event: FormEvent) => {
    event.preventDefault();
    setProposalError(null);
    try {
      await createProposal.mutateAsync({
        proposed_brand_name: propBrandName.trim(),
        name: propName.trim(),
        capacity_kg: propCapacity.trim(),
        product_type: propType,
        description: propDescription.trim(),
      });
      setProposalOpen(false);
      setPropBrandName("");
      setPropName("");
      setPropCapacity("12.5");
      setPropDescription("");
      setFlashMessage(t("depotPortal.offers.proposalSaved"));
    } catch (err) {
      setProposalError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const firstAcqTotal =
    (Number.parseInt(opsDraft.FIRST_ACQUISITION.gasPrice || "0", 10) || 0) +
    (Number.parseInt(opsDraft.FIRST_ACQUISITION.bottlePrice || "0", 10) || 0) +
    (Number.parseInt(opsDraft.FIRST_ACQUISITION.depositAmount || "0", 10) || 0);

  return (
    <div className="space-y-4">
      {/* Bascule Offres / Propositions + bouton d'ajout */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-sm bg-surface-muted p-1">
          <button
            type="button"
            onClick={() => setSubView("offers")}
            className={`min-h-10 rounded-sm px-3.5 text-sm font-bold transition-colors duration-150 ${
              subView === "offers"
                ? "bg-ink-900 text-text-inverse"
                : "text-text-secondary hover:text-text"
            }`}
          >
            {t("depotPortal.offers.subviewOffers")}
          </button>
          <button
            type="button"
            onClick={() => setSubView("proposals")}
            className={`min-h-10 rounded-sm px-3.5 text-sm font-bold transition-colors duration-150 ${
              subView === "proposals"
                ? "bg-ink-900 text-text-inverse"
                : "text-text-secondary hover:text-text"
            }`}
          >
            {t("depotPortal.offers.subviewProposals")}
          </button>
        </div>

        {subView === "offers" ? (
          <Button
            variant="primary"
            disabled={!canMutate}
            onClick={openCreateOfferModal}
            className="min-h-11 px-4 text-base"
          >
            <IconPlus size={18} stroke={2.2} aria-hidden="true" />
            <span>{t("depotPortal.offers.addOffer")}</span>
          </Button>
        ) : (
          <Button
            variant="primary"
            disabled={!canMutate}
            onClick={() => {
              setProposalError(null);
              setProposalOpen(true);
            }}
            className="min-h-11 px-4 text-base"
          >
            <IconPlus size={18} stroke={2.2} aria-hidden="true" />
            <span>{t("depotPortal.offers.addProposal")}</span>
          </Button>
        )}
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
          <button type="button" onClick={() => setFlashMessage(null)} className="text-xs underline">
            {t("errors.close")}
          </button>
        </div>
      )}

      {/* VUE OFFRES DU DÉPÔT */}
      {subView === "offers" && (
        <>
          {offersQuery.isLoading ? (
            <div className="space-y-3">
              <div className="h-32 w-full bg-card animate-skeleton" />
              <div className="h-32 w-full bg-card animate-skeleton" />
            </div>
          ) : offersQuery.error ? (
            <ErrorBanner
              title={t("errors.serverTitle")}
              message={
                offersQuery.error instanceof Error
                  ? offersQuery.error.message
                  : t("errors.serverBody")
              }
              onRetry={() => void offersQuery.refetch()}
            />
          ) : offers.length === 0 ? (
            <EmptyState
              title={t("depotPortal.offers.emptyTitle")}
              body={t("depotPortal.offers.emptyBody")}
              actionLabel={canMutate ? t("depotPortal.offers.addOffer") : undefined}
              onAction={canMutate ? openCreateOfferModal : undefined}
            />
          ) : (
            <div className="space-y-3">
              {offers.map((offer) => (
                <article
                  key={offer.id}
                  className={`overflow-hidden rounded-r-sm border-l-4 bg-card ${
                    offer.is_active ? "border-ink-900" : "border-ink-400"
                  }`}
                >
                  <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5 pb-2.5">
                    <div className="min-w-0">
                      <h2 className="font-display text-xl font-bold uppercase tracking-[0.4px] text-text">
                        {offer.product.brand.name} ·{" "}
                        {formatCapacityKg(offer.product.capacity_kg, i18n.language)}
                      </h2>
                      {offer.notes && (
                        <p className="mt-0.5 text-sm text-text-secondary">{offer.notes}</p>
                      )}
                    </div>
                    <span
                      className={`inline-flex min-h-6 items-center rounded-sm px-2.5 py-0.5 text-xs font-bold ${
                        offer.is_active
                          ? "bg-open-bg text-open"
                          : "bg-surface-muted text-text-secondary"
                      }`}
                    >
                      {offer.is_active
                        ? t("depotPortal.offers.activeBadge")
                        : t("depotPortal.offers.hiddenBadge")}
                    </span>
                  </div>

                  {/* Tarifs par opération */}
                  <div className="space-y-2 bg-price-band px-4 py-2.5">
                    {offer.operations.length === 0 ? (
                      <p className="text-sm text-text-secondary">{t("store.noActiveOperations")}</p>
                    ) : (
                      <ul className="divide-y divide-divider/60">
                        {offer.operations.map((op) => (
                          <li
                            key={op.id}
                            className="flex flex-wrap items-baseline justify-between gap-2 py-1.5 first:pt-0 last:pb-0 text-sm"
                          >
                            <span className="font-bold text-text">
                              {t(`operation.${op.operation_type}`)}
                            </span>
                            <span className="font-mono font-medium tabular text-text-brand">
                              {formatFcfa(op.total_unit_price, i18n.language)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}

                    {offer.exchange_brands.length > 0 && (
                      <div className="flex flex-wrap items-center gap-1.5 pt-1">
                        <span className="text-[11px] font-bold uppercase tracking-[0.3px] text-text-secondary">
                          {t("operation.EXCHANGE")} :
                        </span>
                        {offer.exchange_brands.map((brand) => (
                          <span
                            key={brand.id}
                            className="rounded-sm bg-card px-2 py-0.5 text-xs font-bold text-text"
                          >
                            {brand.name}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Actions sur l'offre */}
                  <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
                    <button
                      type="button"
                      disabled={!canMutate}
                      onClick={() => openEditOfferModal(offer)}
                      className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-ink-900 px-3 text-xs font-bold uppercase tracking-[0.3px] text-text-inverse hover:bg-ink-700 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
                    >
                      <IconEdit size={15} stroke={2} aria-hidden="true" />
                      <span>{t("depotPortal.offers.editOffer")}</span>
                    </button>

                    <button
                      type="button"
                      disabled={!canMutate || updateOffer.isPending}
                      onClick={() => void handleToggleOfferActive(offer)}
                      className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-surface-muted px-3 text-xs font-bold uppercase tracking-[0.3px] text-text hover:bg-border disabled:cursor-not-allowed disabled:text-text-muted"
                    >
                      {offer.is_active ? (
                        <>
                          <IconEyeOff size={15} stroke={2} aria-hidden="true" />
                          <span>{t("depotPortal.offers.hide")}</span>
                        </>
                      ) : (
                        <>
                          <IconEye size={15} stroke={2} aria-hidden="true" />
                          <span>{t("depotPortal.offers.activate")}</span>
                        </>
                      )}
                    </button>

                    {confirmDeleteId === offer.id ? (
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          disabled={deleteOffer.isPending}
                          onClick={() => void handleConfirmDelete(offer.id)}
                          className="inline-flex min-h-10 items-center rounded-sm bg-danger px-3 text-xs font-bold uppercase text-on-action"
                        >
                          {t("depotPortal.offers.confirmDelete")}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="inline-flex min-h-10 items-center rounded-sm bg-surface-muted px-2.5 text-xs font-bold text-text"
                        >
                          {t("depotPortal.offers.cancel")}
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        disabled={!canMutate}
                        onClick={() => setConfirmDeleteId(offer.id)}
                        className="inline-flex min-h-10 items-center gap-1.5 rounded-sm bg-danger-bg px-3 text-xs font-bold uppercase tracking-[0.3px] text-danger hover:bg-danger hover:text-on-action disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
                      >
                        <IconTrash size={15} stroke={2} aria-hidden="true" />
                        <span>{t("depotPortal.offers.deleteOffer")}</span>
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      )}

      {/* VUE PROPOSITIONS CATALOGUE */}
      {subView === "proposals" && (
        <>
          {proposalsQuery.isLoading ? (
            <div className="h-28 w-full bg-card animate-skeleton" />
          ) : proposals.length === 0 ? (
            <EmptyState
              title={t("depotPortal.offers.proposalsEmptyTitle")}
              body={t("depotPortal.offers.proposalsEmptyBody")}
              actionLabel={canMutate ? t("depotPortal.offers.addProposal") : undefined}
              onAction={canMutate ? () => setProposalOpen(true) : undefined}
            />
          ) : (
            <ul className="divide-y divide-divider border-l-4 border-ink-900 bg-card">
              {proposals.map((prop) => (
                <li key={prop.id} className="px-4 py-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <p className="font-sans text-base font-bold text-text">
                        {prop.proposed_brand_name} ·{" "}
                        {formatCapacityKg(prop.capacity_kg, i18n.language)}
                      </p>
                      <p className="text-sm text-text-secondary">
                        {prop.name} · {prop.product_type}
                      </p>
                      {prop.review_note && (
                        <p className="mt-1.5 bg-price-band px-2.5 py-1.5 text-xs text-text-secondary">
                          {prop.review_note}
                        </p>
                      )}
                    </div>
                    <span
                      className={`inline-flex min-h-6 items-center rounded-sm px-2.5 py-0.5 text-xs font-bold ${proposalStatusClass(
                        prop.status,
                      )}`}
                    >
                      {t(`depotPortal.offers.proposalStatus.${prop.status}`)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {/* MODALE CRÉATION / ÉDITION OFFRE */}
      <BottomSheet
        open={offerModalMode !== null}
        title={
          offerModalMode === "edit"
            ? t("depotPortal.offers.editOffer")
            : t("depotPortal.offers.createOfferTitle")
        }
        onClose={() => setOfferModalMode(null)}
      >
        {offerModalMode === "create" && availableProductsForCreate.length === 0 ? (
          <div className="space-y-4">
            <p className="bg-card p-4 text-sm text-text-secondary">
              {t("depotPortal.offers.allProductsUsed")}
            </p>
            <Button
              variant="primary"
              fullWidth
              onClick={() => {
                setOfferModalMode(null);
                setSubView("proposals");
                setProposalOpen(true);
              }}
            >
              {t("depotPortal.offers.addProposal")}
            </Button>
          </div>
        ) : (
          <form onSubmit={(e) => void handleSaveOffer(e)} className="space-y-4">
            {offerError && <ErrorBanner message={offerError} />}

            {offerModalMode === "create" ? (
              <div className="space-y-1.5">
                <label
                  htmlFor="offer-product"
                  className="block text-sm font-bold uppercase tracking-[0.3px] text-text-secondary"
                >
                  {t("depotPortal.offers.fields.product")}
                </label>
                <select
                  id="offer-product"
                  value={selectedProductId}
                  onChange={(e) => {
                    setSelectedProductId(e.target.value);
                    setExchangeBrandIds([]);
                  }}
                  required
                  className="h-12 w-full rounded-t-sm border-b-2 border-ink-900/20 bg-card px-3.5 text-base text-text focus:border-action focus:outline-none"
                >
                  {availableProductsForCreate.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.brand.name} · {formatCapacityKg(p.capacity_kg, i18n.language)} ({p.name})
                    </option>
                  ))}
                </select>
              </div>
            ) : editingOffer ? (
              <div className="border-l-4 border-ink-900 bg-card px-3.5 py-2.5">
                <p className="font-bold text-text">
                  {editingOffer.product.brand.name} ·{" "}
                  {formatCapacityKg(editingOffer.product.capacity_kg, i18n.language)}
                </p>
              </div>
            ) : null}

            <label className="flex min-h-11 cursor-pointer items-center gap-3 bg-card px-3.5 py-2">
              <input
                type="checkbox"
                checked={offerActive}
                onChange={(e) => setOfferActive(e.target.checked)}
                className="h-5 w-5 accent-action"
              />
              <span className="text-sm font-bold text-text">
                {t("depotPortal.offers.fields.isActive")}
              </span>
            </label>

            <TextField
              id="offer-notes"
              label={t("depotPortal.offers.fields.notes")}
              placeholder={t("depotPortal.offers.fields.notesPlaceholder")}
              value={offerNotes}
              onChange={(e) => setOfferNotes(e.target.value)}
            />

            {/* Opérations et tarifs */}
            <div className="space-y-2.5">
              <p className="text-sm font-bold uppercase tracking-[0.3px] text-text-secondary">
                {t("depotPortal.offers.fields.operations")}
              </p>

              {OPERATION_ORDER.map((opType) => {
                const draft = opsDraft[opType];
                return (
                  <div
                    key={opType}
                    className={`border-l-4 bg-card p-3.5 space-y-3 ${
                      draft.enabled ? "border-action" : "border-ink-300"
                    }`}
                  >
                    <label className="flex cursor-pointer items-center gap-2.5">
                      <input
                        type="checkbox"
                        checked={draft.enabled}
                        onChange={(e) =>
                          setOpsDraft((prev) => ({
                            ...prev,
                            [opType]: { ...prev[opType], enabled: e.target.checked },
                          }))
                        }
                        className="h-5 w-5 accent-action"
                      />
                      <span className="font-bold text-text">{t(`operation.${opType}`)}</span>
                    </label>

                    {draft.enabled && (
                      <div className="space-y-3 pt-1">
                        <TextField
                          id={`op-gas-${opType}`}
                          type="number"
                          min={0}
                          step={50}
                          required
                          label={t("depotPortal.offers.fields.gasPrice")}
                          value={draft.gasPrice}
                          onChange={(e) =>
                            setOpsDraft((prev) => ({
                              ...prev,
                              [opType]: { ...prev[opType], gasPrice: e.target.value },
                            }))
                          }
                        />

                        {opType === "FIRST_ACQUISITION" && (
                          <>
                            <div className="grid grid-cols-2 gap-3">
                              <TextField
                                id="op-bottle-first"
                                type="number"
                                min={0}
                                step={100}
                                label={t("depotPortal.offers.fields.bottlePrice")}
                                value={draft.bottlePrice}
                                onChange={(e) =>
                                  setOpsDraft((prev) => ({
                                    ...prev,
                                    FIRST_ACQUISITION: {
                                      ...prev.FIRST_ACQUISITION,
                                      bottlePrice: e.target.value,
                                    },
                                  }))
                                }
                              />
                              <TextField
                                id="op-deposit-first"
                                type="number"
                                min={0}
                                step={100}
                                label={t("depotPortal.offers.fields.depositAmount")}
                                value={draft.depositAmount}
                                onChange={(e) =>
                                  setOpsDraft((prev) => ({
                                    ...prev,
                                    FIRST_ACQUISITION: {
                                      ...prev.FIRST_ACQUISITION,
                                      depositAmount: e.target.value,
                                    },
                                  }))
                                }
                              />
                            </div>
                            <p className="flex items-baseline justify-between bg-price-band px-3 py-2 text-sm">
                              <span className="text-text-secondary">
                                {t("depotPortal.offers.fields.totalUnitPrice")}
                              </span>
                              <span className="font-mono font-bold tabular text-text-brand">
                                {formatFcfa(firstAcqTotal, i18n.language)}
                              </span>
                            </p>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Marques vides acceptées en échange */}
            {opsDraft.EXCHANGE.enabled && (
              <div className="space-y-2 bg-card p-3.5">
                <p className="text-xs font-bold uppercase tracking-[0.3px] text-text-secondary">
                  {t("depotPortal.offers.fields.exchangeBrands")}
                </p>
                <p className="text-xs text-text-secondary">
                  {t("depotPortal.offers.fields.exchangeHint")}
                </p>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {selectableExchangeBrands.map((brand) => (
                    <FilterChip
                      key={brand.id}
                      label={brand.name}
                      selected={exchangeBrandIds.includes(brand.id)}
                      onClick={() => toggleExchangeBrand(brand.id)}
                    />
                  ))}
                </div>
              </div>
            )}

            <Button
              type="submit"
              variant="primary"
              fullWidth
              isLoading={createOffer.isPending || updateOffer.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("auth.saveAction")}
            </Button>
          </form>
        )}
      </BottomSheet>

      {/* MODALE PROPOSITION PRODUIT */}
      <BottomSheet
        open={proposalOpen}
        title={t("depotPortal.offers.proposalTitle")}
        onClose={() => setProposalOpen(false)}
      >
        <form onSubmit={(e) => void handleCreateProposal(e)} className="space-y-4">
          {proposalError && <ErrorBanner message={proposalError} />}

          <TextField
            id="prop-brand"
            required
            label={t("depotPortal.offers.proposalFields.brandName")}
            value={propBrandName}
            onChange={(e) => setPropBrandName(e.target.value)}
          />

          <TextField
            id="prop-name"
            required
            label={t("depotPortal.offers.proposalFields.name")}
            value={propName}
            onChange={(e) => setPropName(e.target.value)}
          />

          <div className="grid grid-cols-2 gap-3">
            <TextField
              id="prop-capacity"
              type="number"
              step="0.1"
              min="0.1"
              required
              label={t("depotPortal.offers.proposalFields.capacityKg")}
              value={propCapacity}
              onChange={(e) => setPropCapacity(e.target.value)}
            />

            <div className="space-y-1.5">
              <label
                htmlFor="prop-type"
                className="block text-sm font-bold uppercase tracking-[0.3px] text-text-secondary"
              >
                {t("depotPortal.offers.proposalFields.productType")}
              </label>
              <select
                id="prop-type"
                value={propType}
                onChange={(e) => setPropType(e.target.value as "BUTANE" | "PROPANE" | "LPG")}
                className="h-12 w-full rounded-t-sm border-b-2 border-ink-900/20 bg-card px-3.5 text-base text-text focus:border-action focus:outline-none"
              >
                <option value="BUTANE">Butane</option>
                <option value="PROPANE">Propane</option>
                <option value="LPG">GPL</option>
              </select>
            </div>
          </div>

          <TextField
            id="prop-desc"
            label={t("depotPortal.offers.proposalFields.description")}
            value={propDescription}
            onChange={(e) => setPropDescription(e.target.value)}
          />

          <Button
            type="submit"
            variant="primary"
            fullWidth
            isLoading={createProposal.isPending}
            loadingLabel={t("auth.saving")}
          >
            {t("depotPortal.offers.addProposal")}
          </Button>
        </form>
      </BottomSheet>
    </div>
  );
}
