/**
 * Coque applicative Faya — Fusion « Braise sur Sable » (A + B).
 * En-tête charbon #181411 + barre basse / rail desktop charbon + fond sable chaud #F2EDE6.
 */

import {
  IconBell,
  IconBuildingStore,
  IconClock,
  IconMapPin,
  IconUser,
} from "@tabler/icons-react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { FayaWordmark } from "../design/FayaLogo";
import { OfflineBanner } from "../design/ui";
import { useAuth } from "../features/auth/AuthContext";
import { getActiveLanguage, setAppLanguage } from "../i18n";
import { useNetworkStatus } from "./NetworkContext";

interface NavEntry {
  to: string;
  label: string;
  icon: typeof IconMapPin;
  matchPrefix?: string;
}

export function Layout() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { isOnline, justRestored, lastSyncIso } = useNetworkStatus();
  const location = useLocation();
  const activeLang = getActiveLanguage();

  const navItems: NavEntry[] = [
    {
      to: "/",
      label: t("nav.depots"),
      icon: IconMapPin,
      matchPrefix: "/depots",
    },
    {
      to: "/orders",
      label: t("nav.orders"),
      icon: IconClock,
    },
    ...(user?.role === "DEPOT_MANAGER"
      ? [
          {
            to: "/depot",
            label: t("nav.depotPortal"),
            icon: IconBuildingStore,
            matchPrefix: "/depot",
          },
        ]
      : []),
    {
      to: user ? "/profile" : "/login",
      label: user ? t("nav.profile") : t("nav.login"),
      icon: IconUser,
      matchPrefix: user ? "/profile" : "/register",
    },
  ];

  const isActiveEntry = (item: NavEntry): boolean => {
    if (item.to === "/") {
      return location.pathname === "/" || location.pathname.startsWith("/depots");
    }
    if (location.pathname === item.to) return true;
    if (item.matchPrefix && location.pathname.startsWith(item.matchPrefix)) return true;
    return false;
  };

  const toggleLanguage = () => {
    setAppLanguage(activeLang === "fr" ? "en" : "fr");
  };

  return (
    <div className="flex min-h-dvh flex-col bg-bg text-text lg:pl-[4.5rem]">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-action focus:px-3 focus:py-2 focus:text-sm focus:font-bold focus:text-on-action"
      >
        {t("app.skipToContent")}
      </a>

      {/* Rail latéral desktop charbon (72 px, ≥ 64 rem) */}
      <aside
        aria-label="Navigation principale"
        className="fixed top-0 bottom-0 left-0 z-40 hidden w-[4.5rem] flex-col items-center border-r border-header-border bg-header-bg py-3 lg:flex"
      >
        <nav className="mt-14 flex w-full flex-col gap-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActiveEntry(item);
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={`relative flex min-h-16 w-full flex-col items-center justify-center gap-1 px-1 text-center text-xs transition-colors duration-150 ${
                  active
                    ? "font-bold text-action"
                    : "font-medium text-text-inverse-muted hover:text-text-inverse"
                }`}
              >
                {active && (
                  <span
                    aria-hidden="true"
                    className="absolute top-2 bottom-2 left-0 w-[3px] rounded-r-full bg-action"
                  />
                )}
                <Icon size={24} stroke={active ? 2 : 1.75} aria-hidden="true" />
                <span className="leading-tight">{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </aside>

      {/* En-tête charbon compact (56 px) */}
      <header className="sticky top-0 z-30 bg-header-bg text-text-inverse">
        <div className="flex h-14 items-center justify-between gap-3 px-4 lg:px-6">
          <Link to="/" className="inline-flex min-h-12 items-center" aria-label={t("app.name")}>
            <FayaWordmark variant="color" size={30} onDark />
          </Link>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={toggleLanguage}
              aria-label={`${t("language.label")}: ${activeLang === "fr" ? t("language.en") : t("language.fr")}`}
              className="touch-target inline-flex h-10 items-center justify-center rounded-sm bg-header-surface px-3 font-mono text-xs font-medium uppercase text-text-inverse hover:bg-ink-700"
            >
              {i18n.language.startsWith("en") ? t("language.shortEn") : t("language.shortFr")}
            </button>

            {user && (
              <Link
                to="/orders"
                aria-label={`${t("nav.orders")} (0)`}
                className="touch-target inline-flex h-10 items-center gap-1 rounded-sm bg-header-surface px-2.5 text-text-inverse hover:bg-ink-700"
              >
                <IconBell size={20} stroke={1.75} aria-hidden="true" />
                <span className="font-mono text-xs font-medium tabular">0</span>
              </Link>
            )}
          </div>
        </div>

        <OfflineBanner
          isOnline={isOnline}
          justRestored={justRestored}
          lastSyncIso={lastSyncIso}
        />
      </header>

      {/* Contenu principal sur fond sable chaud */}
      <main id="main-content" className="flex flex-1 flex-col pb-[calc(3.5rem+var(--safe-bottom))] lg:pb-0">
        <Outlet />
      </main>

      {/* Barre d'onglets mobile charbon (56 px + marge iPhone plafonnée à 12 px) */}
      <nav
        aria-label="Navigation principale"
        className="fixed right-0 bottom-0 left-0 z-40 border-t border-header-border bg-header-bg pb-[var(--safe-bottom)] lg:hidden"
      >
        <div
          className="grid h-14"
          style={{ gridTemplateColumns: `repeat(${navItems.length}, minmax(0, 1fr))` }}
        >
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActiveEntry(item);
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={`relative flex flex-col items-center justify-center gap-0.5 text-xs transition-colors duration-150 ${
                  active ? "font-bold text-action" : "font-medium text-text-inverse-muted"
                }`}
              >
                {active && (
                  <span
                    aria-hidden="true"
                    className="absolute top-0 right-5 left-5 h-[3px] rounded-b-full bg-action"
                  />
                )}
                <Icon size={24} stroke={active ? 2 : 1.75} aria-hidden="true" />
                <span className="leading-none">{item.label}</span>
              </NavLink>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
