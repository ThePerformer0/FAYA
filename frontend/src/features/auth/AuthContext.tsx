import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  apiClient,
  extractApiError,
  refreshAccessToken,
  registerSessionExpiredHandler,
} from "../../api/client";
import type { components } from "../../api/schema";
import { clearAccessToken, setAccessToken } from "../../api/tokenStore";

export type UserMe = components["schemas"]["UserMe"];
export type UserRole = UserMe["role"];
export type RegisterInput = components["schemas"]["RegisterRequest"];
export type LoginInput = components["schemas"]["LoginRequest"];

interface AuthContextValue {
  user: UserMe | null;
  isBootstrapping: boolean;
  login: (input: LoginInput) => Promise<UserMe>;
  register: (input: RegisterInput) => Promise<UserMe>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<UserMe | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserMe | null>(null);
  const [isBootstrapping, setIsBootstrapping] = useState(true);

  const fetchMe = useCallback(async (): Promise<UserMe | null> => {
    const { data, error } = await apiClient.GET("/api/v1/auth/me/");
    if (error || !data) {
      return null;
    }
    setUser(data);
    return data;
  }, []);

  useEffect(() => {
    registerSessionExpiredHandler(() => {
      clearAccessToken();
      setUser(null);
    });

    let active = true;
    (async () => {
      const token = await refreshAccessToken();
      if (token && active) {
        await fetchMe();
      }
      if (active) {
        setIsBootstrapping(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [fetchMe]);

  const login = useCallback(async (input: LoginInput): Promise<UserMe> => {
    const { data, error, response } = await apiClient.POST("/api/v1/auth/login/", {
      body: input,
    });
    if (error || !data) {
      throw extractApiError(error, response.status);
    }
    setAccessToken(data.access_token);
    setUser(data.user);
    return data.user;
  }, []);

  const register = useCallback(async (input: RegisterInput): Promise<UserMe> => {
    const { data, error, response } = await apiClient.POST("/api/v1/auth/register/", {
      body: input,
    });
    if (error || !data) {
      throw extractApiError(error, response.status);
    }
    setAccessToken(data.access_token);
    setUser(data.user);
    return data.user;
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    try {
      await apiClient.POST("/api/v1/auth/logout/");
    } finally {
      clearAccessToken();
      setUser(null);
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isBootstrapping,
      login,
      register,
      logout,
      refreshUser: fetchMe,
    }),
    [user, isBootstrapping, login, register, logout, fetchMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth doit être utilisé dans un AuthProvider.");
  }
  return ctx;
}
