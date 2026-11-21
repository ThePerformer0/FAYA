import { Link, Outlet } from "react-router-dom";

import { useAuth } from "../features/auth/AuthContext";
import { useNetworkStatus } from "./NetworkContext";

export function Layout() {
  const { user, isBootstrapping } = useAuth();
  const { isOnline } = useNetworkStatus();

  return (
    <div className="flex min-h-screen flex-col">
      {!isOnline && (
        <div className="bg-amber-600 px-4 py-1.5 text-center text-xs font-medium text-white">
          Mode hors ligne — consultation uniquement. Les réservations nécessitent une connexion.
        </div>
      )}

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-extrabold tracking-tight text-orange-600">
            Faya
          </Link>

          <nav className="flex items-center gap-4 text-sm font-medium text-slate-700">
            {user?.role === "DEPOT_MANAGER" && (
              <Link to="/depot" className="hover:text-orange-600">
                Mon dépôt
              </Link>
            )}

            {isBootstrapping ? (
              <span className="text-xs text-slate-400">...</span>
            ) : user ? (
              <Link
                to="/profile"
                className="rounded-lg bg-slate-100 px-3 py-1.5 text-slate-800 hover:bg-slate-200"
              >
                {user.full_name}
              </Link>
            ) : (
              <>
                <Link to="/login" className="hover:text-orange-600">
                  Connexion
                </Link>
                <Link
                  to="/register"
                  className="rounded-lg bg-orange-600 px-3 py-1.5 text-white hover:bg-orange-700"
                >
                  Inscription
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
