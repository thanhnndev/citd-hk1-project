/// <reference types="google.maps" />
"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { type PlaceResult } from "@/lib/chat-api";

const HAM_NINH_CENTER = { lat: 10.1835208, lng: 104.0496843 };

function hasLocation(place: PlaceResult): place is PlaceResult & { location: { lat: number; lng: number } } {
  return (
    typeof place.location?.lat === "number" &&
    Number.isFinite(place.location.lat) &&
    typeof place.location.lng === "number" &&
    Number.isFinite(place.location.lng)
  );
}

// Global promise to prevent appending the Google Maps script multiple times across mount cycles
let sdkLoadingPromise: Promise<void> | null = null;

function loadGoogleMapsSdk(token: string): Promise<void> {
  if (window.google?.maps?.marker?.AdvancedMarkerElement) {
    return Promise.resolve();
  }
  if (sdkLoadingPromise) {
    return sdkLoadingPromise;
  }

  sdkLoadingPromise = new Promise<void>((resolve, reject) => {
    const scriptId = "google-maps-sdk";
    let script = document.getElementById(scriptId) as HTMLScriptElement;

    const handleCallback = () => {
      resolve();
    };
    (window as any).initGoogleMapCallback = handleCallback;

    if (!script) {
      script = document.createElement("script");
      script.id = scriptId;
      // Load both maps and marker libraries synchronously in the script bootstrap url
      script.src = `https://maps.googleapis.com/maps/api/js?key=${token}&loading=async&callback=initGoogleMapCallback&libraries=marker`;
      script.async = true;
      script.defer = true;
      script.addEventListener("error", (err) => {
        sdkLoadingPromise = null;
        reject(err);
      });
      document.head.appendChild(script);
    } else {
      script.addEventListener("load", handleCallback);
      script.addEventListener("error", (err) => {
        sdkLoadingPromise = null;
        reject(err);
      });
    }
  });

  return sdkLoadingPromise;
}

type GooglePlaceMapProps = Readonly<{
  places: PlaceResult[];
  selectedPlaceId: string | null;
  onMarkerSelect: (placeId: string) => void;
  missingTokenLabel: string;
  unavailableLabel: string;
  emptyLabel: string;
  selectPlaceLabel: string;
  apiKey: string;
}>;

export function GooglePlaceMap({
  places,
  selectedPlaceId,
  onMarkerSelect,
  missingTokenLabel,
  unavailableLabel,
  emptyLabel,
  selectPlaceLabel,
  apiKey,
}: GooglePlaceMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<any[]>([]);
  const [mapError, setMapError] = useState<string | null>(null);

  const token = apiKey;
  const pinnedPlaces = useMemo(() => places.filter(hasLocation), [places]);

  useEffect(() => {
    if (!token || !containerRef.current) return;

    let active = true;

    async function setupMapAndMarkers() {
      try {
        // 1. Ensure Google Maps SDK (including marker library) is loaded
        await loadGoogleMapsSdk(token);
        if (!active || !containerRef.current) return;

        // 2. Initialize the Map instance if it doesn't exist yet
        let map = mapRef.current;
        if (!map) {
          map = new google.maps.Map(containerRef.current, {
            center: HAM_NINH_CENTER,
            zoom: 12,
            mapId: "DEMO_MAP_ID", // Required for AdvancedMarkerElement
            mapTypeControl: false,
            streetViewControl: false,
            fullscreenControl: false,
            zoomControl: true,
            styles: [
              {
                featureType: "poi",
                elementType: "labels",
                stylers: [{ visibility: "off" }],
              },
              {
                featureType: "transit",
                elementType: "labels",
                stylers: [{ visibility: "off" }],
              },
            ],
          });
          mapRef.current = map;
        }

        // 3. Remove existing markers
        markersRef.current.forEach((marker) => {
          marker.map = null;
        });
        markersRef.current = [];

        if (pinnedPlaces.length === 0) return;

        // 4. Place custom HTML markers using AdvancedMarkerElement from window.google.maps
        markersRef.current = pinnedPlaces.map((place, index) => {
          const isSelected = selectedPlaceId === place.place_id;

          const pinElement = document.createElement("div");
          pinElement.className = [
            "grid size-9 place-items-center rounded-full border-2 text-sm font-bold shadow-md transition-all duration-300 hover:scale-110 cursor-pointer",
            isSelected
              ? "bg-[#0d767d] border-[#f59e0b] text-white ring-4 ring-[#0d767d]/30 scale-110 z-10"
              : "bg-[#f59e0b] border-white text-[#1e293b] hover:bg-[#d97706]"
          ].join(" ");
          pinElement.textContent = String(index + 1);

          const marker = new google.maps.marker.AdvancedMarkerElement({
            map: map!,
            position: { lat: place.location.lat, lng: place.location.lng },
            content: pinElement,
            title: `${selectPlaceLabel}: ${place.display_name}`,
          });

          marker.addListener("click", () => {
            onMarkerSelect(place.place_id);
          });

          return marker;
        });

        // 5. Fit bounds to frame all pins
        const bounds = new google.maps.LatLngBounds();
        pinnedPlaces.forEach((place) => bounds.extend({ lat: place.location.lat, lng: place.location.lng }));
        map.fitBounds(bounds);

        if (pinnedPlaces.length === 1) {
          const listener = google.maps.event.addListener(map, "idle", () => {
            if (map.getZoom()! > 14) map.setZoom(14);
            google.maps.event.removeListener(listener);
          });
        }
      } catch (err) {
        if (active) {
          console.error("Map load failed:", err);
          setMapError("map-unavailable");
        }
      }
    }

    void setupMapAndMarkers();

    return () => {
      active = false;
    };
  }, [token, pinnedPlaces, selectedPlaceId, onMarkerSelect, selectPlaceLabel]);

  // Handle map instance teardown on final component unmount
  useEffect(() => {
    return () => {
      markersRef.current.forEach((marker) => {
        marker.map = null;
      });
      markersRef.current = [];
      mapRef.current = null;
    };
  }, []);

  return (
    <div className="relative h-[450px] overflow-hidden bg-card rounded-[2rem] border shadow-xl shadow-primary/10">
      {/* Map container - always stays in DOM to preserve the instance and avoid quota usage */}
      <div ref={containerRef} className="h-full w-full" />

      {/* Overlay messages */}
      {!token && (
        <div role="status" className="absolute inset-0 grid place-items-center bg-muted p-8 text-center text-sm font-medium text-muted-foreground z-10">
          {missingTokenLabel}
        </div>
      )}

      {token && mapError && (
        <div role="status" className="absolute inset-0 grid place-items-center bg-muted p-8 text-center text-sm font-medium text-muted-foreground z-10">
          {unavailableLabel}
        </div>
      )}

      {token && !mapError && pinnedPlaces.length === 0 && (
        <div role="status" className="absolute inset-0 grid place-items-center bg-muted p-8 text-center text-sm font-medium text-muted-foreground z-10">
          {emptyLabel}
        </div>
      )}
    </div>
  );
}
