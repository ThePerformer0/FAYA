/**
 * File des commandes côté Responsable de dépôt (/depot/orders).
 * Mise en avant des commandes EN_ATTENTE (compte à rebours 15 min) + actions Accepter / Refuser /
 * Valider retrait (paiement + retour bouteille vide) / Annuler non-conformité.
 */

import {
  IconAlertTriangle,
  IconCheck,
  IconClock,
  IconPhone,
  IconX,
} from "@tabler/icons-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import {
  formatCapacityKg,
  formatFcfa,
  formatIsoTimeInPlatformTz,
  formatShortDate,
} from "../../design/formatters";
import { BottomSheet, Button, EmptyState, ErrorBanner, TextField } from "../../design/ui";
import { useNetworkStatus } from "../../shared/NetworkContext";
import {
  isActiveOrderStatus,
  orderAccentClass,
  orderStatusPillClass,
  useAcceptDepotOrder,
  useCancelNonConformityOrder,
  useCountdown,
  useDepotOrders,
  usePickupDepotOrder,
  useRefuseDepotOrder,
  type DepotOrder,
  type PaymentMethod,
} from "../orders/useOrders";
import { usePortalDepot } from "./PortalShell";

type QueueTab = "PENDING" | "CONFIRMED" | "ALL";

function DepotOrderCard({
  order,
  canMutate,
  acceptPending,
  onAccept,
  onRefuse,
  onPickup,
  onNonConformity,
}: {
  order: DepotOrder;
  canMutate: boolean;
  acceptPending: boolean;
  onAccept: (order: DepotOrder) => void;
  onRefuse: (order: DepotOrder) => void;
  onPickup: (order: DepotOrder) => void;
  onNonConformity: (order: DepotOrder) => void;
}) {
  const { t, i18n } = useTranslation();
  const isActive = isActiveOrderStatus(order.status);
  const deadlineIso =
    order.status === "CONFIRMED" ? order.pickup_deadline_at : order.response_deadline_at;
  const countdown = useCountdown(isActive ? deadlineIso : null);
  const item = order.items[0];
  const deadlineHHMM = deadlineIso ? formatIsoTimeInPlatformTz(deadlineIso) : "";

  return (
    <article
      className={`overflow-hidden rounded-r-sm border-l-4 bg-card ${orderAccentClass(order.status)}`}
    >
      {/* En-tête carte : référence + statut + compte à rebours */}
      <div className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5 pb-2.5">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-base font-bold tabular text-text">
              {order.reference}
            </span>
            <span
              className={`inline-flex min-h-6 items-center rounded-sm px-2 py-0.5 text-xs font-bold ${orderStatusPillClass(
                order.status,
              )}`}
            >
              {t(`orders.status.${order.status}`)}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span className="font-bold text-text">{order.customer.full_name}</span>
            <a
              href={`tel:${order.customer.phone}`}
              className="inline-flex items-center gap-1 font-mono text-xs font-medium tabular text-text-brand underline"
            >
              <IconPhone size={14} stroke={2} aria-hidden="true" />
              <span>{order.customer.phone}</span>
            </a>
          </div>
        </div>

        {isActive && (
          <div
            className={`rounded-sm px-2.5 py-1 text-right ${
              countdown.isUrgent || countdown.isExpired
                ? "bg-danger-bg text-danger"
                : "bg-timer-bg text-timer-fg"
            }`}
          >
            <p className="flex items-center justify-end gap-1 text-[10px] font-bold uppercase tracking-[0.4px] opacity-80">
              <IconClock size={12} stroke={2} aria-hidden="true" />
              <span>{deadlineHHMM}</span>
            </p>
            <p className="font-mono text-base font-bold tabular">{countdown.formatted}</p>
          </div>
        )}
      </div>

      {/* Détail article & montant figé */}
      <div className="space-y-1.5 bg-price-band px-4 py-2.5">
        {item && (
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <p className="font-sans text-sm font-bold text-text">
                {item.quantity} × {item.brand_name} ·{" "}
                {formatCapacityKg(item.capacity_kg, i18n.language)}
              </p>
              <p className="text-xs text-text-secondary">
                {t(`operation.${item.operation_type}`)}
                {item.operation_type === "EXCHANGE" && item.exchange_brand_name
                  ? ` · ${item.exchange_brand_name}`
                  : ""}
              </p>
            </div>
            <span className="font-mono text-lg font-bold tabular text-text-brand">
              {formatFcfa(order.total_amount, i18n.language)}
            </span>
          </div>
        )}

        {order.status_reason && (
          <p className="text-xs text-text-secondary">
            {t("orders.reasonPrefix", { reason: order.status_reason })}
          </p>
        )}

        {order.payment && (
          <p className="text-xs font-medium text-text-secondary">
            {t("orders.paymentReceipt", {
              method: t(`orders.paymentMethod.${order.payment.payment_method}`),
              amount: formatFcfa(order.payment.received_amount, i18n.language),
            })}
            {order.payment.external_reference
              ? ` · ${t("orders.paymentRef", { ref: order.payment.external_reference })}`
              : ""}
          </p>
        )}

        <p className="text-[11px] text-text-muted">
          {formatShortDate(order.created_at, i18n.language)} ·{" "}
          {formatIsoTimeInPlatformTz(order.created_at)}
        </p>
      </div>

      {/* Actions selon l'état */}
      {order.status === "PENDING" && (
        <div className="grid grid-cols-2 gap-2 px-4 py-3">
          <button
            type="button"
            disabled={!canMutate || acceptPending}
            onClick={() => onAccept(order)}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-sm bg-action px-3 font-display text-base font-bold uppercase tracking-[0.4px] text-on-action hover:bg-action-pressed disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
          >
            <IconCheck size={18} stroke={2.2} aria-hidden="true" />
            <span>{t("depotPortal.orders.acceptAction")}</span>
          </button>
          <button
            type="button"
            disabled={!canMutate}
            onClick={() => onRefuse(order)}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-sm bg-danger-bg px-3 text-sm font-bold text-danger hover:bg-danger hover:text-on-action disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
          >
            <IconX size={17} stroke={2} aria-hidden="true" />
            <span>{t("depotPortal.orders.refuseAction")}</span>
          </button>
        </div>
      )}

      {order.status === "CONFIRMED" && (
        <div className="flex flex-wrap gap-2 px-4 py-3">
          <button
            type="button"
            disabled={!canMutate}
            onClick={() => onPickup(order)}
            className="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-sm bg-ink-900 px-3 font-display text-base font-bold uppercase tracking-[0.4px] text-text-inverse hover:bg-ink-700 disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
          >
            <IconCheck size={18} stroke={2.2} aria-hidden="true" />
            <span>{t("depotPortal.orders.pickupAction")}</span>
          </button>
          <button
            type="button"
            disabled={!canMutate}
            onClick={() => onNonConformity(order)}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-sm bg-danger-bg px-3 text-xs font-bold text-danger hover:bg-danger hover:text-on-action disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-text-muted"
          >
            <IconAlertTriangle size={16} stroke={2} aria-hidden="true" />
            <span>{t("depotPortal.orders.nonConformityAction")}</span>
          </button>
        </div>
      )}
    </article>
  );
}

export function PortalOrdersPage() {
  const { t, i18n } = useTranslation();
  const { isOnline } = useNetworkStatus();
  const depot = usePortalDepot();
  const canMutate = depot.is_editable && isOnline;

  const [tab, setTab] = useState<QueueTab>("PENDING");
  const [flashMessage, setFlashMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const pendingQuery = useDepotOrders({ status: "PENDING" });
  const confirmedQuery = useDepotOrders({ status: "CONFIRMED" });
  const allQuery = useDepotOrders({ enabled: tab === "ALL" });

  const acceptMutation = useAcceptDepotOrder();
  const refuseMutation = useRefuseDepotOrder();
  const pickupMutation = usePickupDepotOrder();
  const nonConformityMutation = useCancelNonConformityOrder();

  // Modale Refus
  const [refuseTarget, setRefuseTarget] = useState<DepotOrder | null>(null);
  const [refuseReason, setRefuseReason] = useState("");
  const [refuseError, setRefuseError] = useState<string | null>(null);

  // Modale Non-conformité
  const [nonConfTarget, setNonConfTarget] = useState<DepotOrder | null>(null);
  const [nonConfReason, setNonConfReason] = useState("");
  const [nonConfError, setNonConfError] = useState<string | null>(null);

  // Modale Retrait + Paiement
  const [pickupTarget, setPickupTarget] = useState<DepotOrder | null>(null);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>("CASH");
  const [externalRef, setExternalRef] = useState("");
  const [pickupNotes, setPickupNotes] = useState("");
  const [pickupError, setPickupError] = useState<string | null>(null);

  const activeQuery =
    tab === "PENDING" ? pendingQuery : tab === "CONFIRMED" ? confirmedQuery : allQuery;
  const orders = activeQuery.data?.results ?? [];
  const pendingCount = pendingQuery.data?.count ?? 0;
  const confirmedCount = confirmedQuery.data?.count ?? 0;

  const handleAccept = async (order: DepotOrder) => {
    setActionError(null);
    setFlashMessage(null);
    try {
      await acceptMutation.mutateAsync(order.id);
      setFlashMessage(t("depotPortal.orders.acceptedNotice"));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const handleRefuseSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!refuseTarget) return;
    setRefuseError(null);
    try {
      await refuseMutation.mutateAsync({
        orderId: refuseTarget.id,
        reason: refuseReason.trim(),
      });
      setRefuseTarget(null);
      setRefuseReason("");
      setFlashMessage(t("depotPortal.orders.refusedNotice"));
    } catch (err) {
      setRefuseError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const handleNonConfSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!nonConfTarget) return;
    setNonConfError(null);
    try {
      await nonConformityMutation.mutateAsync({
        orderId: nonConfTarget.id,
        reason: nonConfReason.trim(),
      });
      setNonConfTarget(null);
      setNonConfReason("");
      setFlashMessage(t("depotPortal.orders.nonConformityNotice"));
    } catch (err) {
      setNonConfError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const handlePickupSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!pickupTarget) return;
    setPickupError(null);
    try {
      await pickupMutation.mutateAsync({
        orderId: pickupTarget.id,
        body: {
          payment_method: paymentMethod,
          received_amount: pickupTarget.total_amount,
          external_reference: paymentMethod === "MOBILE_MONEY" ? externalRef.trim() : "",
          notes: pickupNotes.trim(),
        },
      });
      setPickupTarget(null);
      setExternalRef("");
      setPickupNotes("");
      setFlashMessage(t("depotPortal.orders.pickedUpNotice"));
    } catch (err) {
      setPickupError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  const pickupItem = pickupTarget?.items[0] ?? null;

  return (
    <div className="space-y-4">
      {/* Sous-onglets file d'attente */}
      <div className="grid grid-cols-3 gap-1 rounded-sm bg-surface-muted p-1">
        <button
          type="button"
          onClick={() => setTab("PENDING")}
          className={`flex min-h-10 items-center justify-center gap-1.5 rounded-sm px-2 text-sm font-bold transition-colors duration-150 ${
            tab === "PENDING"
              ? "bg-ink-900 text-text-inverse"
              : "text-text-secondary hover:text-text"
          }`}
        >
          <span>{t("depotPortal.orders.tabPending")}</span>
          {pendingCount > 0 && (
            <span className="inline-flex min-w-5 items-center justify-center rounded-sm bg-action px-1.5 py-0.5 font-mono text-xs font-bold tabular text-on-action">
              {pendingCount}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setTab("CONFIRMED")}
          className={`flex min-h-10 items-center justify-center gap-1.5 rounded-sm px-2 text-sm font-bold transition-colors duration-150 ${
            tab === "CONFIRMED"
              ? "bg-ink-900 text-text-inverse"
              : "text-text-secondary hover:text-text"
          }`}
        >
          <span>{t("depotPortal.orders.tabConfirmed")}</span>
          {confirmedCount > 0 && (
            <span className="inline-flex min-w-5 items-center justify-center rounded-sm bg-open-bg px-1.5 py-0.5 font-mono text-xs font-bold tabular text-open">
              {confirmedCount}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setTab("ALL")}
          className={`flex min-h-10 items-center justify-center rounded-sm px-2 text-sm font-bold transition-colors duration-150 ${
            tab === "ALL"
              ? "bg-ink-900 text-text-inverse"
              : "text-text-secondary hover:text-text"
          }`}
        >
          {t("depotPortal.orders.tabAll")}
        </button>
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

      {actionError && <ErrorBanner message={actionError} />}

      {activeQuery.isLoading ? (
        <div className="space-y-3">
          <div className="h-36 w-full bg-card animate-skeleton" />
          <div className="h-36 w-full bg-card animate-skeleton" />
        </div>
      ) : activeQuery.error ? (
        <ErrorBanner
          title={t("errors.serverTitle")}
          message={
            activeQuery.error instanceof Error ? activeQuery.error.message : t("errors.serverBody")
          }
          onRetry={() => void activeQuery.refetch()}
        />
      ) : orders.length === 0 ? (
        <EmptyState
          title={
            tab === "PENDING"
              ? t("depotPortal.orders.emptyPendingTitle")
              : tab === "CONFIRMED"
                ? t("depotPortal.orders.emptyConfirmedTitle")
                : t("depotPortal.orders.emptyAllTitle")
          }
          body={
            tab === "PENDING"
              ? t("depotPortal.orders.emptyPendingBody")
              : tab === "CONFIRMED"
                ? t("depotPortal.orders.emptyConfirmedBody")
                : t("depotPortal.orders.emptyAllBody")
          }
        />
      ) : (
        <div className="space-y-3">
          {orders.map((order) => (
            <DepotOrderCard
              key={order.id}
              order={order}
              canMutate={canMutate}
              acceptPending={acceptMutation.isPending}
              onAccept={(o) => void handleAccept(o)}
              onRefuse={(o) => {
                setRefuseError(null);
                setRefuseReason("");
                setRefuseTarget(o);
              }}
              onPickup={(o) => {
                setPickupError(null);
                setPaymentMethod("CASH");
                setExternalRef("");
                setPickupNotes("");
                setPickupTarget(o);
              }}
              onNonConformity={(o) => {
                setNonConfError(null);
                setNonConfReason("");
                setNonConfTarget(o);
              }}
            />
          ))}
        </div>
      )}

      {/* MODALE REFUS (motif obligatoire) */}
      <BottomSheet
        open={Boolean(refuseTarget)}
        title={t("depotPortal.orders.refuseTitle")}
        onClose={() => setRefuseTarget(null)}
      >
        {refuseTarget && (
          <form onSubmit={(e) => void handleRefuseSubmit(e)} className="space-y-4">
            <div className="border-l-4 border-danger bg-card px-3.5 py-2.5">
              <p className="font-mono text-sm font-bold text-text">{refuseTarget.reference}</p>
              <p className="text-sm text-text-secondary">{refuseTarget.customer.full_name}</p>
            </div>
            {refuseError && <ErrorBanner message={refuseError} />}

            <TextField
              id="refuse-reason"
              required
              maxLength={500}
              label={t("depotPortal.orders.refuseReasonLabel")}
              placeholder={t("depotPortal.orders.refuseReasonPlaceholder")}
              value={refuseReason}
              onChange={(e) => setRefuseReason(e.target.value)}
            />

            <Button
              type="submit"
              variant="danger"
              fullWidth
              isLoading={refuseMutation.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("depotPortal.orders.refuseAction")}
            </Button>
          </form>
        )}
      </BottomSheet>

      {/* MODALE ANNULATION NON-CONFORMITÉ BOUTEILLE VIDE */}
      <BottomSheet
        open={Boolean(nonConfTarget)}
        title={t("depotPortal.orders.nonConformityTitle")}
        onClose={() => setNonConfTarget(null)}
      >
        {nonConfTarget && (
          <form onSubmit={(e) => void handleNonConfSubmit(e)} className="space-y-4">
            <p className="border-l-4 border-danger bg-card px-3.5 py-2.5 text-sm text-text-secondary">
              {t("depotPortal.orders.nonConformityHint")}
            </p>
            {nonConfError && <ErrorBanner message={nonConfError} />}

            <TextField
              id="nonconf-reason"
              required
              maxLength={500}
              label={t("depotPortal.orders.nonConformityReasonLabel")}
              placeholder={t("depotPortal.orders.nonConformityReasonPlaceholder")}
              value={nonConfReason}
              onChange={(e) => setNonConfReason(e.target.value)}
            />

            <Button
              type="submit"
              variant="danger"
              fullWidth
              isLoading={nonConformityMutation.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("depotPortal.orders.nonConformityAction")}
            </Button>
          </form>
        )}
      </BottomSheet>

      {/* MODALE VALIDATION RETRAIT + ENCAISSEMENT */}
      <BottomSheet
        open={Boolean(pickupTarget)}
        title={t("depotPortal.orders.pickupTitle")}
        onClose={() => setPickupTarget(null)}
      >
        {pickupTarget && (
          <form onSubmit={(e) => void handlePickupSubmit(e)} className="space-y-4">
            <div className="space-y-2 border-l-4 border-ink-900 bg-card px-3.5 py-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-base font-bold text-text">
                  {pickupTarget.reference}
                </span>
                <span className="font-mono text-lg font-bold tabular text-text-brand">
                  {formatFcfa(pickupTarget.total_amount, i18n.language)}
                </span>
              </div>
              <p className="text-xs text-text-secondary">
                {t("depotPortal.orders.expectedAmountLabel")}
              </p>

              {pickupItem && pickupItem.operation_type !== "FIRST_ACQUISITION" && (
                <p className="bg-soon-bg px-2.5 py-2 text-xs font-bold text-soon">
                  {t("depotPortal.orders.pickupEmptyReminder", {
                    count: pickupItem.quantity,
                    brand:
                      pickupItem.operation_type === "EXCHANGE" && pickupItem.exchange_brand_name
                        ? pickupItem.exchange_brand_name
                        : pickupItem.brand_name,
                    capacity: formatCapacityKg(pickupItem.capacity_kg, i18n.language),
                  })}
                </p>
              )}
            </div>

            {pickupError && <ErrorBanner message={pickupError} />}

            <div className="space-y-1.5">
              <p className="text-sm font-bold uppercase tracking-[0.3px] text-text-secondary">
                {t("depotPortal.orders.paymentMethodLabel")}
              </p>
              <div className="grid grid-cols-2 gap-2">
                {(["CASH", "MOBILE_MONEY"] as PaymentMethod[]).map((method) => (
                  <button
                    key={method}
                    type="button"
                    onClick={() => setPaymentMethod(method)}
                    className={`min-h-12 rounded-sm px-3 text-sm font-bold transition-colors duration-150 ${
                      paymentMethod === method
                        ? "bg-ink-900 text-text-inverse"
                        : "bg-card text-text hover:bg-price-band"
                    }`}
                  >
                    {t(`orders.paymentMethod.${method}`)}
                  </button>
                ))}
              </div>
            </div>

            {paymentMethod === "MOBILE_MONEY" && (
              <TextField
                id="pickup-ext-ref"
                maxLength={120}
                label={t("depotPortal.orders.externalRefLabel")}
                placeholder={t("depotPortal.orders.externalRefPlaceholder")}
                value={externalRef}
                onChange={(e) => setExternalRef(e.target.value)}
              />
            )}

            <TextField
              id="pickup-notes"
              maxLength={500}
              label={t("depotPortal.orders.notesLabel")}
              value={pickupNotes}
              onChange={(e) => setPickupNotes(e.target.value)}
            />

            <Button
              type="submit"
              variant="primary"
              fullWidth
              isLoading={pickupMutation.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("depotPortal.orders.confirmPickup")}
            </Button>
          </form>
        )}
      </BottomSheet>
    </div>
  );
}
