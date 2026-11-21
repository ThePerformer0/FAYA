import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./features/auth/AuthContext";
import { LoginPage } from "./features/auth/LoginPage";
import { ProfilePage } from "./features/auth/ProfilePage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { RegisterPage } from "./features/auth/RegisterPage";
import { Layout } from "./shared/Layout";
import { NetworkProvider } from "./shared/NetworkContext";

function HomePage() {
  const { user } = useAuth();
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-2xl font-bold text-slate-900">
        Trouvez votre bouteille de gaz avant de vous déplacer
      </h1>
      <p className="mt-2 text-sm text-slate-600">
        Socle Jalon 0 opérationnel. La recherche géographique et la carte Leaflet arrivent au
        Jalon 1.
      </p>
      {user && (
        <p className="mt-4 text-sm text-emerald-700">
          Connecté en tant que <strong>{user.full_name}</strong> ({user.role}).
        </p>
      )}
    </div>
  );
}

function DepotPortalPlaceholder() {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-bold text-slate-900">Espace Responsable de dépôt</h1>
      <p className="mt-2 text-sm text-slate-600">
        Accès protégé validé (rôle <code>DEPOT_MANAGER</code>). La gestion des stocks et des
        offres arrive au Jalon 2.
      </p>
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
              <Route path="/" element={<HomePage />} />
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
