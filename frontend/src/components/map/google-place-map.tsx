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
  const [isSdkLoaded, setIsSdkLoaded] = useState(false);
  
  const token = apiKey;
  const pinnedPlaces = useMemo(() => places.filter(hasLocation), [places]);

  // Load Google Maps JS SDK dynamically with async loading + callback
  useEffect(() => {
    if (!token) return;

    if (window.google?.maps) {
      setIsSdkLoaded(true);
      return;
    }

    const scriptId = "google-maps-sdk";
    let script = document.getElementById(scriptId) as HTMLScriptElement;
    
    const handleCallback = () => {
      setIsSdkLoaded(true);
    };
    (window as any).initGoogleMapCallback = handleCallback;

    if (!script) {
      script = document.createElement("script");
      script.id = scriptId;
      script.src = `https://maps.googleapis.com/maps/api/js?key=${token}&loading=async&callback=initGoogleMapCallback`;
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }

    return () => {
      // Keep global callback clean if unmounted before loading
      if (document.getElementById(scriptId) && !(window as any).google?.maps) {
        delete (window as any).initGoogleMapCallback;
      }
    };
  }, [token]);

  // Initialize Map
  useEffect(() => {
    if (!isSdkLoaded || !containerRef.current || !token || pinnedPlaces.length === 0 || mapRef.current) return;

    let active = true;

    async function initMap() {
      try {
        const { Map } = await google.maps.importLibrary("maps") as google.maps.MapsLibrary;
        if (!active || !containerRef.current) return;

        mapRef.current = new Map(containerRef.current, {
          center: HAM_NINH_CENTER,
          zoom: 12,
          mapId: "DEMO_MAP_ID", // Required for AdvancedMarkerElement to work
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: false,
          zoomControl: true,
          // Custom styles for clean, non-cluttered map
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
      } catch {
        if (active) {
          setMapError("map-unavailable");
        }
      }
    }

    void initMap();

    return () => {
      active = false;
      markersRef.current.forEach((marker) => {
        marker.map = null;
      });
      markersRef.current = [];
      mapRef.current = null;
    };
  }, [isSdkLoaded, pinnedPlaces.length, token]);

  // Update Markers and Fit Bounds using AdvancedMarkerElement
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isSdkLoaded) return;

    let active = true;

    async function updateMarkers() {
      try {
        const { AdvancedMarkerElement } = await google.maps.importLibrary("marker") as google.maps.MarkerLibrary;
        const currentMap = mapRef.current;
        if (!active || !currentMap) return;

        // Clear existing markers
        markersRef.current.forEach((marker) => {
          marker.map = null;
        });
        markersRef.current = [];

        // Place custom HTML styled markers
        markersRef.current = pinnedPlaces.map((place, index) => {
          const isSelected = selectedPlaceId === place.place_id;

          // Custom styled HTML element for the marker
          const pinElement = document.createElement("div");
          pinElement.className = [
            "grid size-9 place-items-center rounded-full border-2 text-sm font-bold shadow-md transition-all duration-300 hover:scale-110 cursor-pointer",
            isSelected
              ? "bg-[#0d767d] border-[#f59e0b] text-white ring-4 ring-[#0d767d]/30 scale-110 z-10"
              : "bg-[#f59e0b] border-white text-[#1e293b] hover:bg-[#d97706]"
          ].join(" ");
          pinElement.textContent = String(index + 1);

          const marker = new AdvancedMarkerElement({
            map: currentMap,
            position: { lat: place.location.lat, lng: place.location.lng },
            content: pinElement,
            title: `${selectPlaceLabel}: ${place.display_name}`,
          });

          marker.addListener("click", () => {
            onMarkerSelect(place.place_id);
          });

          return marker;
        });

        // Fit bounds
        if (pinnedPlaces.length > 0) {
          const bounds = new google.maps.LatLngBounds();
          pinnedPlaces.forEach((place) => bounds.extend({ lat: place.location.lat, lng: place.location.lng }));
          currentMap.fitBounds(bounds);

          // Prevent excessive zoom for single marker
          if (pinnedPlaces.length === 1) {
            const listener = google.maps.event.addListener(currentMap, "idle", () => {
              if (currentMap.getZoom()! > 14) currentMap.setZoom(14);
              google.maps.event.removeListener(listener);
            });
          }
        }
      } catch (err) {
        console.error("Failed to load map markers:", err);
      }
    }

    void updateMarkers();

    return () => {
      active = false;
    };
  }, [isSdkLoaded, onMarkerSelect, pinnedPlaces, selectPlaceLabel, selectedPlaceId]);

  if (!token) {
    return <div role="status" className="grid h-80 place-items-center p-8 text-center text-sm font-medium text-muted-foreground">{missingTokenLabel}</div>;
  }

  if (mapError) {
    return <div role="status" className="grid h-80 place-items-center p-8 text-center text-sm font-medium text-muted-foreground">{unavailableLabel}</div>;
  }

  if (pinnedPlaces.length === 0) {
    return <div role="status" className="grid h-80 place-items-center p-8 text-center text-sm font-medium text-muted-foreground">{emptyLabel}</div>;
  }

  return (
    <div className="relative h-80 overflow-hidden bg-muted rounded-t-3xl border-b">
      <div ref={containerRef} className="h-full w-full" />
    </div>
  );
}
