import { useQuery } from "@tanstack/react-query";

import { apiClient, extractApiError } from "../../api/client";
import type { components } from "../../api/schema";
import { useNetworkStatus } from "../../shared/NetworkContext";

export type PublicPlatformSetting = components["schemas"]["PublicPlatformSetting"];

export function usePublicSettings() {
  const { markSynced } = useNetworkStatus();

  return useQuery<PublicPlatformSetting>({
    queryKey: ["settings", "public"],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/settings/public/");
      if (error || !data) {
        const status = (response as Response | undefined)?.status ?? 500;
        throw extractApiError(error, status);
      }
      markSynced(data.server_now);
      return data;
    },
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });
}
