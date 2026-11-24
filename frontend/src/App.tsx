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
    <div className="flex flex-1 flex-col">
      <div className="bg-header-bg px-4 pt-3 pb-5 text-text-inverse">
        <div className="mx-auto max-w-xl">
          <h1 className="font-display text-2xl font-bold uppercase tracking-[0.5px]">
            {t("depotPortal.title")}
          </h1>
        </div>
      </div>
      <div className="mx-auto w-full max-w-xl px-4 py-6">
        <div className="border-l-4 border-ink-900 bg-card p-5">
          <p className="text-base text-text-secondary">{t("depotPortal.body")}</p>
        </div>
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
