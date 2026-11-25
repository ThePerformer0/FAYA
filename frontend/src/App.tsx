import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./features/auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { ProfilePage } from "./features/auth/ProfilePage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { RegisterPage } from "./features/auth/RegisterPage";
import { DepotDetailPage } from "./features/depots/DepotDetailPage";
import { DepotsPage } from "./features/depots/DepotsPage";
import { OrdersPage } from "./features/orders/OrdersPage";
import { PortalDepotInfoPage } from "./features/portal/PortalDepotInfoPage";
import { PortalOffersPage } from "./features/portal/PortalOffersPage";
import { PortalOrdersPage } from "./features/portal/PortalOrdersPage";
import { PortalShell } from "./features/portal/PortalShell";
import { PortalStocksPage } from "./features/portal/PortalStocksPage";
import { Layout } from "./shared/Layout";
import { NetworkProvider } from "./shared/NetworkContext";

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
                <Route path="/depot" element={<PortalShell />}>
                  <Route index element={<Navigate to="stocks" replace />} />
                  <Route path="stocks" element={<PortalStocksPage />} />
                  <Route path="offers" element={<PortalOffersPage />} />
                  <Route path="info" element={<PortalDepotInfoPage />} />
                  <Route path="orders" element={<PortalOrdersPage />} />
                </Route>
              </Route>
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </NetworkProvider>
  );
}

export default App;
