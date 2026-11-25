/**
 * Suivi de commande active (compte à rebours + code retrait + annulation) et historique client.
 * Thème « Braise sur Sable » : zéro bordure 1px grise générique, bloc timer charbon franc.
 */

import {
  IconCheck,
  IconClock,
  IconExternalLink,
  IconPhone,
  IconX,
} from "@tabler/icons-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router-dom";

import {
  formatCapacityKg,
  formatFcfa,
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
import { useAuth } from "../auth/AuthContext";
import {
  isActiveOrderStatus,
  orderAccentClass,
  orderStatusPillClass,
  useCancelCustomerOrder,
  useCountdown,
  useCustomerOrders,
  type CustomerOrder,
  type OrderStatus,
} from "./useOrders";

const HISTORY_STATUS_FILTERS: OrderStatus[] = ["PICKED_UP", "REFUSED", "CANCELLED", "EXPIRED"];

function ActiveOrderHero({
  order,
  onRequestCancel,
  canCancel,
}: {
  order: CustomerOrder;
  onRequestCancel: (order: CustomerOrder) => void;
  canCancel: boolean;
}) {
  const { t, i18n } = useTranslation();
  const isConfirmed = order.status === "CONFIRMED";
  const deadlineIso = isConfirmed ? order.pickup_deadline_at : order.response_deadline_at;
  const countdown = useCountdown(deadlineIso);
  const item = order.items[0];
  const deadlineHHMM = deadlineIso ? formatIsoTimeInPlatformTz(deadlineIso) : "";

  return (
    <section
      aria-label={t("orders.activeTitle")}
      className={`overflow-hidden rounded-r-sm border-l-4 bg-card ${orderAccentClass(order.status)}`}
    >
      {/* En-tête charbon : code retrait + statut + compte à rebours */}
      <div className="bg-timer-bg px-4 py-4 text-timer-fg">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.6px] text-text-inverse-muted">
              {t("orders.referenceLabel")}
            </p>
            <p className="mt-0.5 font-mono text-2xl font-bold tracking-[1px] tabular text-timer-fg">
              {order.reference}
            </p>
          </div>
          <span
            className={`inline-flex min-h-6 items-center rounded-sm px-2.5 py-0.5 text-xs font-bold ${orderStatusPillClass(
              order.status,
            )}`}
          >
            {t(`orders.status.${order.status}`)}
          </span>
        </div>

        {/* Bloc compte à rebours */}
        <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2 border-t border-header-border pt-3">
          <div className="flex items-center gap-1.5 text-xs font-medium text-text-inverse-muted">
            <IconClock size={15} stroke={1.8} aria-hidden="true" />
            <span>
              {countdown.isExpired
                ? t("orders.countdown.expiredLabel")
                : isConfirmed
                  ? t("orders.countdown.confirmedLabel", { time: deadlineHHMM })
                  : t("orders.countdown.pendingLabel", { time: deadlineHHMM })}
            </span>
          </div>
          <p
            className={`font-mono text-2xl font-bold tabular ${
              countdown.isUrgent || countdown.isExpired ? "text-timer-urgent" : "text-timer-fg"
            }`}
          >
            {countdown.formatted}
          </p>
        </div>
      </div>

      {/* Corps dépôt & article figé */}
      <div className="space-y-3 px-4 py-4">
        <div>
          <h2 className="font-display text-xl font-bold uppercase tracking-[0.4px] text-text">
            {order.depot.name}
          </h2>
          <p className="text-sm text-text-secondary">
            {order.depot.address}
            {order.depot.neighborhood ? ` · ${order.depot.neighborhood}` : ""}
          </p>
        </div>

        {item && (
          <div className="space-y-2 bg-price-band px-3.5 py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-sans text-base font-bold text-text">
                {item.quantity} × {item.brand_name} ·{" "}
                {formatCapacityKg(item.capacity_kg, i18n.language)}
              </p>
              <p className="font-mono text-lg font-bold tabular text-text-brand">
                {formatFcfa(order.total_amount, i18n.language)}
              </p>
            </div>
            <p className="text-xs font-medium text-text-secondary">
              {t(`operation.${item.operation_type}`)} ·{" "}
              {t(`orders.paymentStatus.${order.payment_status}`)}
            </p>

            {item.operation_type === "REFILL" && (
              <p className="border-l-2 border-ink-900 pl-2.5 text-xs font-medium text-text">
                {t("orders.bringEmptySameBrand", {
                  count: item.quantity,
                  brand: item.brand_name,
                  capacity: formatCapacityKg(item.capacity_kg, i18n.language),
                })}
              </p>
            )}
            {item.operation_type === "EXCHANGE" && item.exchange_brand_name && (
              <p className="border-l-2 border-action pl-2.5 text-xs font-medium text-text">
                {t("orders.bringEmptyExchange", {
                  count: item.quantity,
                  brand: item.exchange_brand_name,
                  capacity: formatCapacityKg(item.capacity_kg, i18n.language),
                })}
              </p>
            )}
          </div>
        )}

        {/* Actions directes : Appeler / Fiche dépôt / Annuler */}
        <div className="grid grid-cols-2 gap-2 pt-1">
          <a
            href={`tel:${order.depot.phone}`}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-sm bg-ink-900 px-3 text-sm font-bold text-text-inverse hover:bg-ink-700"
          >
            <IconPhone size={17} stroke={1.8} aria-hidden="true" />
            <span>{t("store.call")}</span>
          </a>
          <Link
            to={`/depots/${order.depot.id}`}
            className="inline-flex min-h-11 items-center justify-center gap-1.5 rounded-sm bg-surface-muted px-3 text-sm font-bold text-text hover:bg-border"
          >
            <IconExternalLink size={17} stroke={1.8} aria-hidden="true" />
            <span>{t("orders.viewDepot")}</span>
          </Link>
        </div>

        <button
          type="button"
          disabled={!canCancel}
          onClick={() => onRequestCancel(order)}
          className="inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-sm bg-danger-bg px-3 text-sm font-bold text-danger hover:bg-danger hover:text-on-action disabled:cursor-not-allowed disabled:opacity-50"
        >
          <IconX size={17} stroke={2} aria-hidden="true" />
          <span>{t("orders.cancelAction")}</span>
        </button>
      </div>
    </section>
  );
}

export function OrdersPage() {
  const { t, i18n } = useTranslation();
  const { user, isBootstrapping } = useAuth();
  const { isOnline } = useNetworkStatus();
  const navigate = useNavigate();
  const location = useLocation();
  const justCreated = Boolean((location.state as { created?: boolean } | null)?.created);

  const [statusFilter, setStatusFilter] = useState<OrderStatus | undefined>(undefined);
  const [cancelTarget, setCancelTarget] = useState<CustomerOrder | null>(null);
  const [cancelReason, setCancelReason] = useState("");
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [flashMessage, setFlashMessage] = useState<string | null>(
    justCreated ? t("store.orderCreatedNotice") : null,
  );

  const isCustomer = user?.role === "CUSTOMER";
  const allOrdersQuery = useCustomerOrders({ enabled: isCustomer });
  const filteredQuery = useCustomerOrders({
    status: statusFilter,
    enabled: isCustomer && Boolean(statusFilter),
  });
  const cancelMutation = useCancelCustomerOrder();

  const handleCancelSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!cancelTarget) return;
    setCancelError(null);
    try {
      await cancelMutation.mutateAsync({
        orderId: cancelTarget.id,
        reason: cancelReason.trim(),
      });
      setCancelTarget(null);
      setCancelReason("");
      setFlashMessage(t("orders.cancelledNotice"));
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : t("errors.serverBody"));
    }
  };

  if (isBootstrapping) {
    return (
      <div className="mx-auto w-full max-w-xl px-4 py-8">
        <div className="h-36 w-full bg-card animate-skeleton" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex flex-1 flex-col">
        <div className="bg-header-bg px-4 pt-3 pb-5 text-text-inverse">
          <div className="mx-auto max-w-xl">
            <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
              {t("orders.title")}
            </h1>
          </div>
        </div>
        <div className="mx-auto w-full max-w-xl px-4 py-5">
          <EmptyState
            title={t("orders.loginRequiredTitle")}
            body={t("orders.loginRequiredBody")}
            actionLabel={t("orders.loginAction")}
            onAction={() => navigate("/login", { state: { from: "/orders" } })}
          />
        </div>
      </div>
    );
  }

  if (user.role === "DEPOT_MANAGER") {
    return (
      <div className="flex flex-1 flex-col">
        <div className="bg-header-bg px-4 pt-3 pb-5 text-text-inverse">
          <div className="mx-auto max-w-xl">
            <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
              {t("orders.title")}
            </h1>
          </div>
        </div>
        <div className="mx-auto w-full max-w-xl px-4 py-5">
          <EmptyState
            title={t("orders.managerNoticeTitle")}
            body={t("orders.managerNoticeBody")}
            actionLabel={t("orders.goPortalOrders")}
            onAction={() => navigate("/depot/orders")}
          />
        </div>
      </div>
    );
  }

  const allOrders = allOrdersQuery.data?.results ?? [];
  const activeOrder = allOrders.find((o) => isActiveOrderStatus(o.status)) ?? null;
  const historySource = statusFilter
    ? (filteredQuery.data?.results ?? [])
    : allOrders.filter((o) => !isActiveOrderStatus(o.status));

  return (
    <div className="flex flex-1 flex-col">
      <div className="bg-header-bg px-4 pt-3 pb-5 text-text-inverse">
        <div className="mx-auto max-w-xl">
          <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
            {t("orders.title")}
          </h1>
        </div>
      </div>

      <div className="mx-auto w-full max-w-xl space-y-6 px-4 py-5">
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

        {allOrdersQuery.isLoading ? (
          <div className="space-y-3">
            <div className="h-48 w-full bg-card animate-skeleton" />
            <div className="h-24 w-full bg-card animate-skeleton" />
          </div>
        ) : allOrdersQuery.error ? (
          <ErrorBanner
            title={t("errors.serverTitle")}
            message={
              allOrdersQuery.error instanceof Error
                ? allOrdersQuery.error.message
                : t("errors.serverBody")
            }
            onRetry={() => void allOrdersQuery.refetch()}
          />
        ) : allOrders.length === 0 ? (
          <EmptyState
            title={t("orders.emptyTitle")}
            body={t("orders.emptyBody")}
            actionLabel={t("orders.findDepot")}
            onAction={() => navigate("/")}
          />
        ) : (
          <>
            {activeOrder && (
              <ActiveOrderHero
                order={activeOrder}
                canCancel={isOnline}
                onRequestCancel={(order) => {
                  setCancelError(null);
                  setCancelReason("");
                  setCancelTarget(order);
                }}
              />
            )}

            {/* Section Historique */}
            <section aria-labelledby="orders-history-heading" className="space-y-3">
              <h2
                id="orders-history-heading"
                className="font-display text-lg font-bold uppercase tracking-[0.5px] text-text"
              >
                {t("orders.historyTitle")}
              </h2>

              <div className="flex flex-wrap items-center gap-1.5">
                <FilterChip
                  label={t("orders.allStatuses")}
                  selected={statusFilter === undefined}
                  onClick={() => setStatusFilter(undefined)}
                />
                {HISTORY_STATUS_FILTERS.map((st) => (
                  <FilterChip
                    key={st}
                    label={t(`orders.status.${st}`)}
                    selected={statusFilter === st}
                    onClick={() => setStatusFilter(statusFilter === st ? undefined : st)}
                  />
                ))}
              </div>

              {historySource.length === 0 ? (
                <p className="bg-surface-muted p-4 text-sm text-text-secondary">
                  {t("orders.emptyTitle")}
                </p>
              ) : (
                <ul className="space-y-2.5">
                  {historySource.map((order) => {
                    const item = order.items[0];
                    return (
                      <li
                        key={order.id}
                        className={`overflow-hidden rounded-r-sm border-l-4 bg-card ${orderAccentClass(
                          order.status,
                        )}`}
                      >
                        <div className="px-4 pt-3.5 pb-2.5">
                          <div className="flex flex-wrap items-start justify-between gap-2">
                            <div>
                              <p className="font-mono text-sm font-bold tabular text-text">
                                {order.reference}
                              </p>
                              <p className="font-display text-lg font-bold uppercase tracking-[0.3px] text-text">
                                {order.depot.name}
                              </p>
                            </div>
                            <span
                              className={`inline-flex min-h-6 items-center rounded-sm px-2 py-0.5 text-xs font-bold ${orderStatusPillClass(
                                order.status,
                              )}`}
                            >
                              {t(`orders.status.${order.status}`)}
                            </span>
                          </div>

                          {item && (
                            <p className="mt-1 text-sm text-text-secondary">
                              {item.quantity} × {item.brand_name} ·{" "}
                              {formatCapacityKg(item.capacity_kg, i18n.language)} ·{" "}
                              {t(`operation.${item.operation_type}`)}
                            </p>
                          )}

                          {order.status_reason && (
                            <p className="mt-1.5 text-xs text-text-secondary">
                              {t("orders.reasonPrefix", { reason: order.status_reason })}
                            </p>
                          )}

                          {order.counted_as_no_show && (
                            <p className="mt-1 inline-flex rounded-sm bg-danger-bg px-2 py-0.5 text-xs font-bold text-danger">
                              {t("orders.noShowTag")}
                            </p>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2 bg-price-band px-4 py-2 text-xs">
                          <span className="text-text-muted">
                            {formatShortDate(order.created_at, i18n.language)} ·{" "}
                            {formatIsoTimeInPlatformTz(order.created_at)}
                            {order.payment && (
                              <>
                                {" · "}
                                {t("orders.paymentReceipt", {
                                  method: t(`orders.paymentMethod.${order.payment.payment_method}`),
                                  amount: formatFcfa(order.payment.received_amount, i18n.language),
                                })}
                                {order.payment.external_reference
                                  ? ` (${t("orders.paymentRef", { ref: order.payment.external_reference })})`
                                  : ""}
                              </>
                            )}
                          </span>
                          <span className="font-mono text-sm font-bold tabular text-text">
                            {formatFcfa(order.total_amount, i18n.language)}
                          </span>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </>
        )}
      </div>

      {/* Modale de confirmation d'annulation client */}
      <BottomSheet
        open={Boolean(cancelTarget)}
        title={t("orders.cancelSheetTitle")}
        onClose={() => setCancelTarget(null)}
      >
        {cancelTarget && (
          <form onSubmit={(e) => void handleCancelSubmit(e)} className="space-y-4">
            <p className="border-l-4 border-ink-900 bg-card px-3.5 py-2.5 text-sm text-text-secondary">
              {t("orders.cancelSheetHint")}
            </p>
            {cancelError && <ErrorBanner message={cancelError} />}

            <TextField
              id="cancel-reason"
              label={t("orders.cancelReasonLabel")}
              placeholder={t("orders.cancelReasonPlaceholder")}
              maxLength={500}
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
            />

            <Button
              type="submit"
              variant="danger"
              fullWidth
              isLoading={cancelMutation.isPending}
              loadingLabel={t("auth.saving")}
            >
              {t("orders.confirmCancel")}
            </Button>
          </form>
        )}
      </BottomSheet>
    </div>
  );
}
