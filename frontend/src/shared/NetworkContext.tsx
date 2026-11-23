import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

interface NetworkContextValue {
  isOnline: boolean;
  justRestored: boolean;
  lastSyncIso: string | null;
  markSynced: (iso?: string) => void;
}

const NetworkContext = createContext<NetworkContextValue>({
  isOnline: true,
  justRestored: false,
  lastSyncIso: null,
  markSynced: () => undefined,
});

export function NetworkProvider({ children }: { children: ReactNode }) {
  const [isOnline, setIsOnline] = useState<boolean>(() => navigator.onLine);
  const [justRestored, setJustRestored] = useState(false);
  const [lastSyncIso, setLastSyncIso] = useState<string | null>(() =>
    navigator.onLine ? new Date().toISOString() : null,
  );
  const timerRef = useRef<number | null>(null);

  const markSynced = useCallback((iso?: string) => {
    setLastSyncIso(iso ?? new Date().toISOString());
  }, []);

  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      setJustRestored(true);
      setLastSyncIso(new Date().toISOString());
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      timerRef.current = window.setTimeout(() => {
        setJustRestored(false);
      }, 3000);
    };

    const handleOffline = () => {
      setIsOnline(false);
      setJustRestored(false);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  return (
    <NetworkContext.Provider value={{ isOnline, justRestored, lastSyncIso, markSynced }}>
      {children}
    </NetworkContext.Provider>
  );
}

export function useNetworkStatus(): NetworkContextValue {
  return useContext(NetworkContext);
}
