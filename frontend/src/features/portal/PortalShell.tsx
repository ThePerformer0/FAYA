/**
 * Coque partagée du Portail Responsable de dépôt (/depot/*).
 * En-tête charbon #181411 + barre d'onglets portail (Stock, Offres, Dépôt, Commandes) +
 * bandeaux de statut (en attente / lecture seule).
 */

import {
  IconAlertTriangle,
  IconBox,
  IconBuildingStore,
  IconClipboardList,
  IconInfoCircle,
  IconTag,
} from "@tabler/icons-react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet, useOutletContext } from "react-router-dom";

import { ErrorBanner, OpenStatusChip } from "../../design/ui";
import { useManagedDepot, type ManagedDepot } from "./useDepotPortal";

export interface PortalOutletContext {
  depot: ManagedDepot;
}

export function usePortalDepot(): ManagedDepot {
  return useOutletContext<PortalOutletContext>().depot;
}

function statusPillClass(status: ManagedDepot["status"]): string {
  if (status === "ACTIVE") return "bg-open-bg text-open";
  if (status === "PENDING") return "bg-soon-bg text-soon";
  return "bg-danger-bg text-danger";
}

export function PortalShell() {
  const { t } = useTranslation();
  const { data: depot, isLoading, error, refetch } = useManagedDepot();

  const tabs = [
    { to: "/depot/stocks", label: t("depotPortal.tabs.stocks"), icon: IconBox },
    { to: "/depot/offers", label: t("depotPortal.tabs.offers"), icon: IconTag },
    { to: "/depot/info", label: t("depotPortal.tabs.info"), icon: IconBuildingStore },
    { to: "/depot/orders", label: t("depotPortal.tabs.orders"), icon: IconClipboardList },
  ];

  if (isLoading) {
    return (
      <div className="flex flex-1 flex-col">
        <div className="bg-header-bg px-4 pt-3 pb-5">
          <div className="mx-auto max-w-2xl space-y-2">
            <div className="h-7 w-48 bg-header-surface animate-skeleton" />
            <div className="h-4 w-64 bg-header-surface animate-skeleton" />
          </div>
        </div>
        <div className="mx-auto w-full max-w-2xl space-y-3 px-4 py-6">
          <div className="h-24 w-full bg-card animate-skeleton" />
          <div className="h-24 w-full bg-card animate-skeleton" />
        </div>
      </div>
    );
  }

  if (error || !depot) {
    return (
      <div className="mx-auto w-full max-w-2xl px-4 py-6">
        <ErrorBanner
          title={t("errors.serverTitle")}
          message={error instanceof Error ? error.message : t("errors.serverBody")}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col">
      {/* En-tête charbon avec identité du dépôt et onglets portail */}
      <div className="bg-header-bg text-text-inverse">
        <div className="mx-auto max-w-2xl px-4 pt-3 pb-3">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs font-bold uppercase tracking-[0.5px] text-text-inverse-muted">
                {t("depotPortal.title")}
              </p>
              <h1 className="mt-0.5 font-display text-2xl font-bold uppercase tracking-[0.5px] text-text-inverse">
                {depot.name}
              </h1>
              <p className="mt-0.5 text-xs text-text-inverse-muted">
                {depot.neighborhood ? `${depot.neighborhood} · ` : ""}
                {depot.address}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              <span
                className={`inline-flex min-h-6 items-center rounded-sm px-2.5 py-0.5 text-xs font-bold ${statusPillClass(
                  depot.status,
                )}`}
              >
                {t(`depotPortal.status.${depot.status}`)}
              </span>
              {depot.status === "ACTIVE" && (
                <OpenStatusChip
                  openStatus={depot.open_status}
                  closingTime={depot.closing_time}
                  reopensAt={depot.reopens_at}
                />
              )}
            </div>
          </div>

          {/* Barre d'onglets horizontaux du portail */}
          <nav
            aria-label={t("depotPortal.title")}
            className="mt-4 -mx-1 grid grid-cols-4 gap-1"
          >
            {tabs.map((tab) => {
              const Icon = tab.icon;
              return (
                <NavLink
                  key={tab.to}
                  to={tab.to}
                  className={({ isActive }) =>
                    `relative flex min-h-11 items-center justify-center gap-1.5 rounded-t-sm px-2 text-sm font-bold transition-colors duration-150 ${
                      isActive
                        ? "bg-bg text-text"
                        : "bg-header-surface/70 text-text-inverse-muted hover:bg-header-surface hover:text-text-inverse"
                    }`
                  }
                >
                  <Icon size={17} stroke={1.9} aria-hidden="true" className="shrink-0" />
                  <span className="truncate">{tab.label}</span>
                </NavLink>
              );
            })}
          </nav>
        </div>
      </div>

      {/* Bandeaux d'état opérationnel (PENDING / lecture seule) */}
      <div className="mx-auto w-full max-w-2xl px-4 pt-4">
        {depot.status === "PENDING" && (
          <div
            role="status"
            className="mb-4 flex items-start gap-2.5 border-l-4 border-action bg-soon-bg px-3.5 py-3 text-sm text-soon"
          >
            <IconInfoCircle size={19} stroke={1.8} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>{t("depotPortal.banners.pending")}</p>
          </div>
        )}

        {!depot.is_editable && (
          <div
            role="alert"
            className="mb-4 flex items-start gap-2.5 border-l-4 border-danger bg-danger-bg px-3.5 py-3 text-sm text-danger"
          >
            <IconAlertTriangle size={19} stroke={1.8} className="mt-0.5 shrink-0" aria-hidden="true" />
            <p>
              {t("depotPortal.banners.readOnly", {
                status: t(`depotPortal.status.${depot.status}`),
              })}
            </p>
          </div>
        )}
      </div>

      {/* Contenu de l'onglet actif */}
      <div className="mx-auto w-full max-w-2xl flex-1 px-4 pb-8">
        <Outlet context={{ depot } satisfies PortalOutletContext} />
      </div>
    </div>
  );
}
