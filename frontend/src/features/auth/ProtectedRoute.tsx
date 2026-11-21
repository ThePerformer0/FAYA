import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuth, type UserRole } from "./AuthContext";

interface ProtectedRouteProps {
  allowedRoles?: UserRole[];
}

export function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
  const { user, isBootstrapping } = useAuth();
  const location = useLocation();

  if (isBootstrapping) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <p className="text-sm text-slate-500">Vérification de la session...</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return (
      <div className="mx-auto max-w-md rounded-xl border border-amber-200 bg-amber-50 p-6 text-center">
        <h1 className="text-lg font-semibold text-amber-900">Accès non autorisé</h1>
        <p className="mt-2 text-sm text-amber-800">
          Votre compte ({user.role}) ne dispose pas des droits nécessaires pour accéder à cet
          espace.
        </p>
      </div>
    );
  }

  return <Outlet />;
}
