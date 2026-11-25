/**
 * Hooks TanStack Query typés + compte à rebours temps réel pour les commandes (Jalon 3).
 * Polling intelligent (15 s) actif uniquement quand l'onglet est visible et qu'une commande active existe.
 */

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiClient, extractApiError } from "../../api/client";
import type { components } from "../../api/schema";
import { useNetworkStatus } from "../../shared/NetworkContext";

export type CustomerOrder = components["schemas"]["CustomerOrder"];
export type DepotOrder = components["schemas"]["DepotOrder"];
export type OrderItem = components["schemas"]["OrderItem"];
export type OrderStatus = components["schemas"]["OrderStatusEnum"];
export type PaymentMethod = components["schemas"]["PaymentMethodEnum"];
export type PaymentStatus = components["schemas"]["PaymentStatusEnum"];
export type PaymentRecord = components["schemas"]["PaymentRecord"];
export type OrderCreatePayload = components["schemas"]["OrderCreateRequestRequest"];
export type OrderPickupPayload = components["schemas"]["OrderPickupRequestRequest"];
export type PaginatedCustomerOrderList = components["schemas"]["PaginatedCustomerOrderList"];
export type PaginatedDepotOrderList = components["schemas"]["PaginatedDepotOrderList"];

export const ACTIVE_ORDER_STATUSES: ReadonlySet<OrderStatus> = new Set(["PENDING", "CONFIRMED"]);

function resolveStatus(response: unknown): number {
  return (response as Response | undefined)?.status ?? 500;
}

export function isActiveOrderStatus(status: OrderStatus): boolean {
  return ACTIVE_ORDER_STATUSES.has(status);
}

export function orderStatusPillClass(status: OrderStatus): string {
  if (status === "CONFIRMED") return "bg-open-bg text-open";
  if (status === "PENDING") return "bg-soon-bg text-soon";
  if (status === "PICKED_UP") return "bg-ink-900 text-text-inverse";
  if (status === "REFUSED" || status === "EXPIRED") return "bg-danger-bg text-danger";
  return "bg-surface-muted text-text-secondary";
}

export function orderAccentClass(status: OrderStatus): string {
  if (status === "PENDING") return "border-action";
  if (status === "CONFIRMED") return "border-open";
  if (status === "REFUSED" || status === "EXPIRED") return "border-danger";
  if (status === "PICKED_UP") return "border-ink-900";
  return "border-ink-400";
}

/* === Hooks Client (/api/v1/orders/...) === */

export function useCustomerOrders(
  options: { status?: OrderStatus; enabled?: boolean; page?: number } = {},
) {
  const { markSynced } = useNetworkStatus();
  const { status, enabled = true, page = 1 } = options;

  return useQuery<PaginatedCustomerOrderList>({
    queryKey: ["orders", "customer", { status, page }],
    enabled,
    queryFn: async () => {
      const query: Record<string, string | number> = { page_size: 20 };
      if (status) query.status = status;
      if (page > 1) query.page = page;

      const { data, error, response } = await apiClient.GET("/api/v1/orders/", {
        params: { query },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      markSynced();
      return data;
    },
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    refetchInterval: (query) => {
      const items = query.state.data?.results ?? [];
      const hasActive = items.some((o) => isActiveOrderStatus(o.status));
      return hasActive ? 15_000 : false;
    },
  });
}

export function useCreateOrder() {
  const queryClient = useQueryClient();
  return useMutation<CustomerOrder, unknown, OrderCreatePayload>({
    mutationFn: async (body) => {
      const { data, error, response } = await apiClient.POST("/api/v1/orders/", { body });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
    },
  });
}

export function useCancelCustomerOrder() {
  const queryClient = useQueryClient();
  return useMutation<CustomerOrder, unknown, { orderId: string; reason?: string }>({
    mutationFn: async ({ orderId, reason }) => {
      const { data, error, response } = await apiClient.POST("/api/v1/orders/{order_id}/cancel/", {
        params: { path: { order_id: orderId } },
        body: { reason: reason ?? "" },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

/* === Hooks Responsable (/api/v1/depot/orders/...) === */

export function useDepotOrders(
  options: { status?: OrderStatus; enabled?: boolean; page?: number } = {},
) {
  const { markSynced } = useNetworkStatus();
  const { status, enabled = true, page = 1 } = options;

  return useQuery<PaginatedDepotOrderList>({
    queryKey: ["orders", "depot", { status, page }],
    enabled,
    queryFn: async () => {
      const query: Record<string, string | number> = { page_size: 20 };
      if (status) query.status = status;
      if (page > 1) query.page = page;

      const { data, error, response } = await apiClient.GET("/api/v1/depot/orders/", {
        params: { query },
      });
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      markSynced();
      return data;
    },
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

export function useAcceptDepotOrder() {
  const queryClient = useQueryClient();
  return useMutation<DepotOrder, unknown, string>({
    mutationFn: async (orderId) => {
      const { data, error, response } = await apiClient.POST(
        "/api/v1/depot/orders/{order_id}/accept/",
        { params: { path: { order_id: orderId } } },
      );
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
  });
}

export function useRefuseDepotOrder() {
  const queryClient = useQueryClient();
  return useMutation<DepotOrder, unknown, { orderId: string; reason: string }>({
    mutationFn: async ({ orderId, reason }) => {
      const { data, error, response } = await apiClient.POST(
        "/api/v1/depot/orders/{order_id}/refuse/",
        {
          params: { path: { order_id: orderId } },
          body: { reason },
        },
      );
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stock-movements"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function usePickupDepotOrder() {
  const queryClient = useQueryClient();
  return useMutation<DepotOrder, unknown, { orderId: string; body: OrderPickupPayload }>({
    mutationFn: async ({ orderId, body }) => {
      const { data, error, response } = await apiClient.POST(
        "/api/v1/depot/orders/{order_id}/pickup/",
        {
          params: { path: { order_id: orderId } },
          body,
        },
      );
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stock-movements"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

export function useCancelNonConformityOrder() {
  const queryClient = useQueryClient();
  return useMutation<DepotOrder, unknown, { orderId: string; reason: string }>({
    mutationFn: async ({ orderId, reason }) => {
      const { data, error, response } = await apiClient.POST(
        "/api/v1/depot/orders/{order_id}/cancel-non-conformity/",
        {
          params: { path: { order_id: orderId } },
          body: { reason },
        },
      );
      if (error || !data) {
        throw extractApiError(error, resolveStatus(response));
      }
      return data;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["orders"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stocks"] });
      void queryClient.invalidateQueries({ queryKey: ["portal", "stock-movements"] });
      void queryClient.invalidateQueries({ queryKey: ["depots"] });
    },
  });
}

/* === Compte à rebours temps réel === */

export interface CountdownState {
  remainingSeconds: number;
  isExpired: boolean;
  isUrgent: boolean;
  formatted: string;
}

function formatRemaining(totalSec: number): string {
  const clamped = Math.max(0, Math.floor(totalSec));
  const hours = Math.floor(clamped / 3600);
  const minutes = Math.floor((clamped % 3600) / 60);
  const seconds = clamped % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  if (hours > 0) {
    return `${hours}h ${pad(minutes)}:${pad(seconds)}`;
  }
  return `${pad(minutes)}:${pad(seconds)}`;
}

export function useCountdown(deadlineIso: string | null | undefined): CountdownState {
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!deadlineIso) return;
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [deadlineIso]);

  if (!deadlineIso) {
    return { remainingSeconds: 0, isExpired: true, isUrgent: false, formatted: "00:00" };
  }

  const targetMs = new Date(deadlineIso).getTime();
  const remainingSeconds = Number.isNaN(targetMs)
    ? 0
    : Math.max(0, Math.floor((targetMs - nowMs) / 1000));

  return {
    remainingSeconds,
    isExpired: remainingSeconds <= 0,
    isUrgent: remainingSeconds > 0 && remainingSeconds <= 300,
    formatted: formatRemaining(remainingSeconds),
  };
}
