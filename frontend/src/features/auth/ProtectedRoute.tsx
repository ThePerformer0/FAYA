import { useTranslation } from "react-i18next";
import { Navigate, Outlet, useLocation, useNavigate } from "react-router-dom";

import { Button, ErrorBanner } from "../../design/ui";
import { useAuth, type UserRole } from "./AuthContext";

interface ProtectedRouteProps {
  allowedRoles?: UserRole[];
}

export function ProtectedRoute({ allowedRoles }: ProtectedRouteProps) {
  const { t } = useTranslation();
  const { user, isBootstrapping } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  if (isBootstrapping) {
    return (
      <div className="mx-auto flex w-full max-w-md flex-col gap-3 px-4 py-10">
        <div className="h-8 w-48 rounded-sm bg-surface-muted animate-skeleton" />
        <div className="h-32 w-full rounded-lg bg-surface-muted animate-skeleton" />
        <p className="text-sm text-text-secondary">{t("auth.checkingSession")}</p>
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return (
      <div className="mx-auto w-full max-w-md px-4 py-6 space-y-4">
        <ErrorBanner
          title={t("errors.forbiddenTitle")}
          message={t("errors.forbiddenBody")}
        />
        <Button variant="secondary" fullWidth onClick={() => navigate("/")}>
          {t("errors.backHome")}
        </Button>
      </div>
    );
  }

  return <Outlet />;
}
