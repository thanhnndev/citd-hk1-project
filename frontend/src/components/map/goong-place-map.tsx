"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";

import { type PlaceResult } from "@/lib/chat-api";

function hasLocation(place: PlaceResult): place is PlaceResult & { location: { lat: number; lng: number } } {
  return (
    typeof place.location?.lat === "number" &&
    Number.isFinite(place.location.lat) &&
    typeof place.location.lng === "number" &&
    Number.isFinite(place.location.lng)
  );
}

type GoongPlaceMapProps = Readonly<{
  places: PlaceResult[];
  selectedPlaceId: string | null;
  onMarkerSelect: (placeId: string) => void;
  missingTokenLabel: string;
  emptyLabel: string;
  selectPlaceLabel: string;
}>;

export function GoongPlaceMap({
  places,
  selectedPlaceId,
  onMarkerSelect,
  missingTokenLabel,
  emptyLabel,
  selectPlaceLabel,
}: GoongPlaceMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const markersRef = useRef<mapboxgl.Marker[]>([]);
  const [mapError, setMapError] = useState<string | null>(null);
  const token = process.env.NEXT_PUBLIC_GOONG_MAPTILES_KEY;
  const pinnedPlaces = useMemo(() => places.filter(hasLocation), [places]);

  useEffect(() => {
    if (!containerRef.current || !token || mapRef.current) return;

    try {
      mapRef.current = new mapboxgl.Map({
        container: containerRef.current,
        style: `https://tiles.goong.io/assets/goong_map_web.json?api_key=${token}`,
        center: pinnedPlaces[0] ? [pinnedPlaces[0].location.lng, pinnedPlaces[0].location.lat] : [103.995, 10.19],
        zoom: pinnedPlaces.length > 0 ? 12 : 10,
      });
      mapRef.current.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
      mapRef.current.on("error", () => setMapError("map-unavailable"));
    } catch {
      setMapError("map-unavailable");
    }

    return () => {
      markersRef.current.forEach((marker) => marker.remove());
      markersRef.current = [];
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, [pinnedPlaces, token]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = pinnedPlaces.map((place, index) => {
      const markerElement = document.createElement("button");
      markerElement.type = "button";
      markerElement.textContent = String(index + 1);
      markerElement.setAttribute("aria-label", `${selectPlaceLabel}: ${place.display_name}`);
      markerElement.className = [
        "grid size-10 place-items-center rounded-full border-2 text-sm font-bold shadow-lg transition hover:scale-110",
        selectedPlaceId === place.place_id ? "border-secondary bg-primary text-primary-foreground" : "border-card bg-secondary text-secondary-foreground",
      ].join(" ");
      markerElement.addEventListener("click", () => onMarkerSelect(place.place_id));

      return new mapboxgl.Marker({ element: markerElement })
        .setLngLat([place.location.lng, place.location.lat])
        .addTo(map);
    });

    if (pinnedPlaces.length > 0) {
      const bounds = new mapboxgl.LngLatBounds();
      pinnedPlaces.forEach((place) => bounds.extend([place.location.lng, place.location.lat]));
      map.fitBounds(bounds, { padding: 56, maxZoom: 14, duration: 500 });
    }
  }, [onMarkerSelect, pinnedPlaces, selectPlaceLabel, selectedPlaceId]);

  if (!token) {
    return <div className="grid h-80 place-items-center p-8 text-center text-sm font-medium text-muted-foreground">{missingTokenLabel}</div>;
  }

  if (mapError) {
    return <div className="grid h-80 place-items-center p-8 text-center text-sm font-medium text-muted-foreground">{emptyLabel}</div>;
  }

  return (
    <div className="relative h-80 overflow-hidden bg-muted">
      <div ref={containerRef} className="h-full w-full" />
      {pinnedPlaces.length === 0 && (
        <div className="absolute inset-0 grid place-items-center bg-background/80 p-8 text-center text-sm font-medium text-muted-foreground">
          {emptyLabel}
        </div>
      )}
    </div>
  );
}
