import { useTranslation } from "react-i18next";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./features/auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { ProfilePage } from "./features/auth/ProfilePage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { RegisterPage } from "./features/auth/RegisterPage";
import { DepotDetailPage } from "./features/depots/DepotDetailPage";
import { DepotsPage } from "./features/depots/DepotsPage";
import { OrdersPage } from "./features/orders/OrdersPage";
import { Layout } from "./shared/Layout";
import { NetworkProvider } from "./shared/NetworkContext";

function DepotPortalPlaceholder() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto w-full max-w-xl px-4 py-6">
      <div className="rounded-lg border-card border-border-strong bg-bg p-5">
        <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px] text-text">
          {t("depotPortal.title")}
        </h1>
        <p className="mt-2 text-base text-text-secondary">{t("depotPortal.body")}</p>
      </div>
    </div>
  );
}

export function App() {
  return (
    <NetworkProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<DepotsPage />} />
              <Route path="/depots/:depotId" element={<DepotDetailPage />} />
              <Route path="/orders" element={<OrdersPage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />

              <Route element={<ProtectedRoute />}>
                <Route path="/profile" element={<ProfilePage />} />
              </Route>

              <Route element={<ProtectedRoute allowedRoles={["DEPOT_MANAGER"]} />}>
                <Route path="/depot" element={<DepotPortalPlaceholder />} />
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </NetworkProvider>
  );
}

export default App;
