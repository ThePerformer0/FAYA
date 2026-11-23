import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { apiClient, extractApiError } from "../../api/client";
import type { components } from "../../api/schema";
import { useNetworkStatus } from "../../shared/NetworkContext";

export type Brand = components["schemas"]["Brand"];
export type OperationType = components["schemas"]["OperationTypeEnum"];
export type PublicDepotList = components["schemas"]["PublicDepotList"];
export type PublicDepotDetail = components["schemas"]["PublicDepotDetail"];
export type PublicDepotOffer = components["schemas"]["PublicDepotOffer"];
export type PublicOfferOperation = components["schemas"]["PublicOfferOperation"];
export type PaginatedDepots = components["schemas"]["PaginatedPublicDepotListList"];

export interface DepotSearchFilters {
  q?: string;
  brand?: string;
  capacityKg?: string;
  operation?: OperationType;
  openNow?: boolean;
  lat?: number;
  lng?: number;
  radiusKm?: number;
  page?: number;
}

export function useBrands() {
  return useQuery<Brand[]>({
    queryKey: ["catalog", "brands"],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/catalog/brands/");
      if (error || !data) {
        const status = (response as Response | undefined)?.status ?? 500;
        throw extractApiError(error, status);
      }
      return data;
    },
    staleTime: 5 * 60_000,
  });
}

export function useDepotsSearch(filters: DepotSearchFilters) {
  const { markSynced } = useNetworkStatus();

  return useQuery<PaginatedDepots>({
    queryKey: ["depots", "search", filters],
    queryFn: async () => {
      const query: Record<string, string | number | boolean> = {};
      if (filters.q?.trim()) query.q = filters.q.trim();
      if (filters.brand) query.brand = filters.brand;
      if (filters.capacityKg) query.capacity_kg = filters.capacityKg;
      if (filters.operation) query.operation = filters.operation;
      if (filters.openNow) query.open_now = true;
      if (filters.lat !== undefined && filters.lng !== undefined) {
        query.lat = filters.lat;
        query.lng = filters.lng;
        if (filters.radiusKm !== undefined) {
          query.radius_km = filters.radiusKm;
        }
      }
      if (filters.page && filters.page > 1) {
        query.page = filters.page;
      }

      const { data, error, response } = await apiClient.GET("/api/v1/depots/", {
        params: { query },
      });
      if (error || !data) {
        throw extractApiError(error, response.status);
      }
      markSynced();
      return data;
    },
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useDepotDetail(depotId: string | undefined) {
  const { markSynced } = useNetworkStatus();

  return useQuery<PublicDepotDetail>({
    queryKey: ["depots", "detail", depotId],
    enabled: Boolean(depotId),
    queryFn: async () => {
      if (!depotId) {
        throw new Error("Identifiant de dépôt manquant.");
      }
      const { data, error, response } = await apiClient.GET("/api/v1/depots/{depot_id}/", {
        params: { path: { depot_id: depotId } },
      });
      if (error || !data) {
        throw extractApiError(error, response.status);
      }
      markSynced();
      return data;
    },
    staleTime: 30_000,
  });
}

/** Retourne le prix unitaire minimum parmi toutes les opérations actives d'un dépôt. */
export function getDepotMinPrice(depot: Pick<PublicDepotList, "offers">): number | null {
  let min: number | null = null;
  for (const offer of depot.offers) {
    for (const op of offer.operations) {
      if (min === null || op.total_unit_price < min) {
        min = op.total_unit_price;
      }
    }
  }
  return min;
}
