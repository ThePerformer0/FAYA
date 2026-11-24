/**
 * Hooks TanStack Query typés pour le Portail Responsable de dépôt (/api/v1/depot/...).
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiClient, extractApiError } from "../../api/client";
import type { components } from "../../api/schema";
import { useNetworkStatus } from "../../shared/NetworkContext";

export type ManagedDepot = components["schemas"]["ManagedDepot"];
export type ManagedDepotUpdatePayload = components["schemas"]["PatchedManagedDepotUpdateRequest"];
export type ManagedOffer = components["schemas"]["ManagedOffer"];
export type ManagedOfferCreatePayload = components["schemas"]["ManagedOfferCreateRequest"];
export type ManagedOfferUpdatePayload = components["schemas"]["PatchedManagedOfferUpdateRequest"];
export type ManagedOfferOperationInput = components["schemas"]["ManagedOfferOperationInputRequest"];
export type ManagedProductProposal = components["schemas"]["ManagedProductProposal"];
export type ManagedProductProposalCreatePayload =
  components["schemas"]["ManagedProductProposalCreateRequest"];
export type DepotStock = components["schemas"]["DepotStock"];
export type StockCategory = components["schemas"]["CategoryEnum"];
export type StockMovement = components["schemas"]["StockMovement"];
export type StockMovementType = components["schemas"]["StockMovementMovementTypeEnum"];
export type StockAdjustMovementType = components["schemas"]["StockAdjustRequestMovementTypeEnum"];
export type StockRestockPayload = components["schemas"]["StockRestockRequestRequest"];
export type StockAdjustPayload = components["schemas"]["StockAdjustRequestRequest"];
export type StockScrapPayload = components["schemas"]["StockScrapRequestRequest"];
export type StockMutationResponse = components["schemas"]["StockMutationResponse"];
export type CatalogProduct = components["schemas"]["Product"];
export type PaginatedDepotStockList = components["schemas"]["PaginatedDepotStockList"];
export type PaginatedStockMovementList = components["schemas"]["PaginatedStockMovementList"];
export type PaginatedManagedOfferList = components["schemas"]["PaginatedManagedOfferList"];
export type PaginatedManagedProductProposalList =
  components["schemas"]["PaginatedManagedProductProposalList"];

function resolveStatus(response: unknown): number {
  return (response as Response | undefined)?.status ?? 500;
}

export function useManagedDepot() {
  const { markSynced } = useNetworkStatus();
  return useQuery<ManagedDepot>({
    queryKey: ["portal", "depot"],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/depot/");
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      markSynced();
      return data;
    },
    staleTime: 30_000,
  });
}

export function useUpdateManagedDepot() {
  const queryClient = useQueryClient();
  return useMutation<ManagedDepot, unknown, ManagedDepotUpdatePayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.PATCH("/api/v1/depot/", { body });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["portal", "depot"], updated);
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useCatalogProducts() {
  return useQuery<CatalogProduct[]>({
    queryKey: ["catalog", "products", "all"],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/catalog/products/", {
        params: { query: { page_size: 50 } },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data.results;
    },
    staleTime: 5 * 60_000,
  });
}

export interface StockListFilters {
  category?: StockCategory;
  product?: string;
  page?: number;
}

export function useManagedStocks(filters: StockListFilters = {}) {
  const { markSynced } = useNetworkStatus();
  return useQuery<PaginatedDepotStockList>({
    queryKey: ["portal", "stocks", filters],
    queryFn: async () => {
      const query: Record<string, string | number> = { page_size: 50 };
      if (filters.category) query.category = filters.category;
      if (filters.product) query.product = filters.product;
      if (filters.page && filters.page > 1) query.page = filters.page;

      const { data, error, response } = await apiClient.GET("/api/v1/depot/stocks/", {
        params: { query },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      markSynced();
      return data;
    },
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export interface MovementListFilters {
  category?: StockCategory;
  movementType?: StockMovementType;
  product?: string;
  page?: number;
}

export function useManagedStockMovements(filters: MovementListFilters = {}) {
  const { markSynced } = useNetworkStatus();
  return useQuery<PaginatedStockMovementList>({
    queryKey: ["portal", "stock-movements", filters],
    queryFn: async () => {
      const query: Record<string, string | number> = { page_size: 20 };
      if (filters.category) query.category = filters.category;
      if (filters.movementType) query.movement_type = filters.movementType;
      if (filters.product) query.product = filters.product;
      if (filters.page && filters.page > 1) query.page = filters.page;

      const { data, error, response } = await apiClient.GET("/api/v1/depot/stock-movements/", {
        params: { query },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      markSynced();
      return data;
    },
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useRestockStock() {
  const queryClient = useQueryClient();
  return useMutation<StockMutationResponse, unknown, StockRestockPayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.POST("/api/v1/depot/stocks/restock/", {
        body,
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stock-movements"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useAdjustStock() {
  const queryClient = useQueryClient();
  return useMutation<StockMutationResponse, unknown, StockAdjustPayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.POST("/api/v1/depot/stocks/adjust/", {
        body,
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stock-movements"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useScrapStock() {
  const queryClient = useQueryClient();
  return useMutation<StockMutationResponse, unknown, StockScrapPayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.POST("/api/v1/depot/stocks/scrap/", {
        body,
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stock-movements"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useManagedOffers() {
  const { markSynced } = useNetworkStatus();
  return useQuery<PaginatedManagedOfferList>({
    queryKey: ["portal", "offers"],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/depot/offers/", {
        params: { query: { page_size: 50 } },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      markSynced();
      return data;
    },
    staleTime: 20_000,
  });
}

export function useCreateManagedOffer() {
  const queryClient = useQueryClient();
  return useMutation<ManagedOffer, unknown, ManagedOfferCreatePayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.POST("/api/v1/depot/offers/", { body });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "offers"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useUpdateManagedOffer() {
  const queryClient = useQueryClient();
  return useMutation<
    ManagedOffer,
    unknown,
    { offerId: string; body: ManagedOfferUpdatePayload }
  >({
    mutationFn: async ({ offerId, body }) => {
      const { data, error, response } = await apiClient.PATCH("/api/v1/depot/offers/{offer_id}/", {
        params: { path: { offer_id: offerId } },
        body,
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "offers"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useDeleteManagedOffer() {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, string>({
    mutationFn: async (offerId) => {
      const { error, response } = await apiClient.DELETE("/api/v1/depot/offers/{offer_id}/", {
        params: { path: { offer_id: offerId } },
      });
      if (error) {
        throw extractApiError(error, resolveStatus(response));
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "offers"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useManagedProposals() {
  return useQuery<PaginatedManagedProductProposalList>({
    queryKey: ["portal", "proposals"],
    queryFn: async () => {
      const { data, error, response } = await apiClient.GET("/api/v1/depot/proposals/", {
        params: { query: { page_size: 50 } },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    staleTime: 30_000,
  });
}

export function useCreateManagedProposal() {
  const queryClient = useQueryClient();
  return useMutation<ManagedProductProposal, unknown, ManagedProductProposalCreatePayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.POST("/api/v1/depot/proposals/", { body });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portal", "proposals"] });
    },
  });
}
