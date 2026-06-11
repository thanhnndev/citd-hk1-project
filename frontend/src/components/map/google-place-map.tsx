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
}>;

export function GooglePlaceMap({
  places,
  selectedPlaceId,
  onMarkerSelect,
  missingTokenLabel,
  unavailableLabel,
  emptyLabel,
  selectPlaceLabel,
}: GooglePlaceMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.Marker[]>([]);
  const [mapError, setMapError] = useState<string | null>(null);
  const [isSdkLoaded, setIsSdkLoaded] = useState(false);
  
  // Use Google Maps JS API Key (exposes to browser safely via NEXT_PUBLIC prefix)
  const token = process.env.NEXT_PUBLIC_GOOGLE_MAPS_JS_API_KEY;
  const pinnedPlaces = useMemo(() => places.filter(hasLocation), [places]);

  // Load Google Maps JS SDK dynamically
  useEffect(() => {
    if (!token) return;

    if (window.google?.maps) {
      setIsSdkLoaded(true);
      return;
    }

    const scriptId = "google-maps-sdk";
    let script = document.getElementById(scriptId) as HTMLScriptElement;
    
    const handleLoad = () => setIsSdkLoaded(true);
    const handleError = () => setMapError("map-unavailable");

    if (!script) {
      script = document.createElement("script");
      script.id = scriptId;
      script.src = `https://maps.googleapis.com/maps/api/js?key=${token}`;
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }

    script.addEventListener("load", handleLoad);
    script.addEventListener("error", handleError);

    return () => {
      script.removeEventListener("load", handleLoad);
      script.removeEventListener("error", handleError);
    };
  }, [token]);

  // Initialize Map
  useEffect(() => {
    if (!isSdkLoaded || !containerRef.current || !token || pinnedPlaces.length === 0 || mapRef.current) return;

    try {
      mapRef.current = new google.maps.Map(containerRef.current, {
        center: HAM_NINH_CENTER,
        zoom: 12,
        mapTypeControl: false,
        streetViewControl: false,
        fullscreenControl: false,
        zoomControl: true,
        // Premium minimalist styles (remove Google Maps default POI clutter)
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
      setMapError("map-unavailable");
    }

    return () => {
      markersRef.current.forEach((marker) => marker.setMap(null));
      markersRef.current = [];
      mapRef.current = null;
    };
  }, [isSdkLoaded, pinnedPlaces.length, token]);

  // Update Markers and Fit Bounds
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !isSdkLoaded) return;

    // Clear existing markers
    markersRef.current.forEach((marker) => marker.setMap(null));

    // Place custom styled pins
    markersRef.current = pinnedPlaces.map((place, index) => {
      const isSelected = selectedPlaceId === place.place_id;

      const marker = new google.maps.Marker({
        position: { lat: place.location.lat, lng: place.location.lng },
        map,
        title: `${selectPlaceLabel}: ${place.display_name}`,
        label: {
          text: String(index + 1),
          color: isSelected ? "#ffffff" : "#1e293b",
          fontWeight: "bold",
          fontSize: "13px",
        },
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 18,
          // Match primary theme color (teal) when selected, and secondary color (orange) when idle
          fillColor: isSelected ? "#0d767d" : "#f59e0b",
          fillOpacity: 1,
          strokeColor: isSelected ? "#f59e0b" : "#ffffff",
          strokeWeight: 2,
          labelOrigin: new google.maps.Point(0, 0),
        },
      });

      marker.addListener("click", () => {
        onMarkerSelect(place.place_id);
      });

      return marker;
    });

    // Fit bounds dynamically to frame all recommended pins
    if (pinnedPlaces.length > 0) {
      const bounds = new google.maps.LatLngBounds();
      pinnedPlaces.forEach((place) => bounds.extend({ lat: place.location.lat, lng: place.location.lng }));
      map.fitBounds(bounds);

      // Prevent zooming in too close if there is only a single result
      if (pinnedPlaces.length === 1) {
        const listener = google.maps.event.addListener(map, "idle", () => {
          if (map.getZoom()! > 14) map.setZoom(14);
          google.maps.event.removeListener(listener);
        });
      }
    }
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
