/**
 * Carte Leaflet + OpenStreetMap chargée dynamiquement à la demande (DESIGN_SYSTEM §3.5).
 * Tuiles monochromes CSS + repères DivIcon Faya (jamais d'images PNG Leaflet par défaut).
 */

import "leaflet/dist/leaflet.css";
import type L from "leaflet";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { formatFcfa } from "../../design/formatters";
import { normalizeStoreOpenStatus } from "../../design/statusStyles";
import { getDepotMinPrice, type PublicDepotList } from "./useDepots";

const DOUALA_DEFAULT: [number, number] = [4.0511, 9.7679];

const FLAME_SVG =
  '<svg width="16" height="16" viewBox="0 0 32 32" fill="none" aria-hidden="true">' +
  '<path d="M16 3C20.2 7.5 25 11.8 25 18.2C25 23.8 21 29 16 29C11 29 7 23.8 7 18.2C7 11.8 11.8 7.5 16 3Z" fill="currentColor"/>' +
  "</svg>";

export interface MapDepotPoint {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  open_status: string;
  offers: PublicDepotList["offers"];
}

interface DepotsMapProps {
  depots: MapDepotPoint[];
  selectedDepotId?: string | null;
  onSelectDepot?: (depotId: string) => void;
  userCoords?: { lat: number; lng: number } | null;
  className?: string;
}

export default function DepotsMap({
  depots,
  selectedDepotId = null,
  onSelectDepot,
  userCoords = null,
  className = "h-full w-full",
}: DepotsMapProps) {
  const { i18n } = useTranslation();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const leafletRef = useRef<typeof L | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const userLayerRef = useRef<L.LayerGroup | null>(null);
  const hasFitBoundsRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);

  // Initialisation paresseuse de Leaflet dans le conteneur
  useEffect(() => {
    let cancelled = false;

    async function initMap() {
      const container = containerRef.current;
      if (!container || mapRef.current) return;

      const leafletModule = await import("leaflet");
      if (cancelled) return;
      const leaflet = leafletModule.default ?? leafletModule;
      leafletRef.current = leaflet;

      const initialCenter: [number, number] = userCoords
        ? [userCoords.lat, userCoords.lng]
        : depots.length > 0
          ? [depots[0].latitude, depots[0].longitude]
          : DOUALA_DEFAULT;

      const map = leaflet.map(container, {
        center: initialCenter,
        zoom: 13,
        zoomControl: true,
      });

      leaflet
        .tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: "&copy; OpenStreetMap contributors",
          maxZoom: 19,
        })
        .addTo(map);

      markersLayerRef.current = leaflet.layerGroup().addTo(map);
      userLayerRef.current = leaflet.layerGroup().addTo(map);
      mapRef.current = map;
      setMapReady(true);

      // Recalcule la taille après montage (utile dans un panneau ou onglet)
      window.setTimeout(() => map.invalidateSize(), 60);
    }

    void initMap();

    return () => {
      cancelled = true;
      setMapReady(false);
      if (mapRef.current) {
        mapRef.current.remove();
        mapRef.current = null;
        markersLayerRef.current = null;
        userLayerRef.current = null;
        hasFitBoundsRef.current = false;
      }
    };
    // Initialisation unique au montage du composant
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Mise à jour des repères dépôts (DivIcon Faya)
  useEffect(() => {
    const map = mapRef.current;
    const leaflet = leafletRef.current;
    const layer = markersLayerRef.current;
    if (!map || !leaflet || !layer) return;

    layer.clearLayers();

    const bounds: [number, number][] = [];

    for (const depot of depots) {
      const status = normalizeStoreOpenStatus(depot.open_status);
      const isSelected = depot.id === selectedDepotId;
      const statusClass =
        status === "OPEN"
          ? "faya-map-pin--open"
          : status === "CLOSING_SOON"
            ? "faya-map-pin--closing-soon"
            : "faya-map-pin--closed";

      const minPrice = isSelected ? getDepotMinPrice(depot) : null;
      const priceTag =
        isSelected && minPrice !== null
          ? `<span class="faya-map-pin__price">${formatFcfa(minPrice, i18n.language)}</span>`
          : "";

      const html =
        `<div class="faya-map-pin ${statusClass} ${isSelected ? "faya-map-pin--selected" : ""}">` +
        `<span class="faya-map-pin__disc">${FLAME_SVG}</span>` +
        priceTag +
        "</div>";

      const icon = leaflet.divIcon({
        className: "faya-map-marker-wrapper",
        html,
        iconSize: [40, isSelected && minPrice !== null ? 58 : 40],
        iconAnchor: [20, 20],
      });

      const marker = leaflet.marker([depot.latitude, depot.longitude], {
        icon,
        title: depot.name,
        zIndexOffset: isSelected ? 500 : status === "CLOSED" ? 0 : 100,
      });

      marker.on("click", () => {
        onSelectDepot?.(depot.id);
      });

      marker.addTo(layer);
      bounds.push([depot.latitude, depot.longitude]);
    }

    if (userCoords) {
      bounds.push([userCoords.lat, userCoords.lng]);
    }

    if (!hasFitBoundsRef.current && bounds.length > 0) {
      hasFitBoundsRef.current = true;
      if (bounds.length === 1) {
        map.setView(bounds[0], 15);
      } else {
        map.fitBounds(bounds, { padding: [44, 44], maxZoom: 15 });
      }
    }
  }, [mapReady, depots, selectedDepotId, onSelectDepot, i18n.language, userCoords]);

  // Repère position du client
  useEffect(() => {
    const leaflet = leafletRef.current;
    const layer = userLayerRef.current;
    const map = mapRef.current;
    if (!leaflet || !layer || !map) return;

    layer.clearLayers();
    if (!userCoords) return;

    const userIcon = leaflet.divIcon({
      className: "faya-map-marker-wrapper",
      html: '<div class="faya-user-dot"></div>',
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    });
    leaflet.marker([userCoords.lat, userCoords.lng], { icon: userIcon, interactive: false }).addTo(layer);
    map.panTo([userCoords.lat, userCoords.lng]);
  }, [mapReady, userCoords]);

  return (
    <div
      ref={containerRef}
      className={`faya-map bg-surface-muted ${className}`}
      aria-label="Carte des dépôts de gaz"
    />
  );
}
