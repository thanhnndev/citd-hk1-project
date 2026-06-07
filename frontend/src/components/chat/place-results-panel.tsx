"use client";

import { BadgeCheck, X } from "lucide-react";
import type { PlaceResult } from "@/lib/chat-api";
import { PlaceCard, type PlaceCardTranslations } from "./place-card";

interface PlaceResultsPanelProps {
  places: PlaceResult[];
  translations: PlaceCardTranslations & {
    placeResultsHeading: string;
  };
  mobileOpen: boolean;
  onMobileClose: () => void;
}

export function PlaceResultsPanel({
  places,
  translations,
  mobileOpen,
  onMobileClose,
}: PlaceResultsPanelProps) {
  if (places.length === 0) return null;

  const cards = (
    <div className="space-y-5 p-5">
      {places.slice(0, 6).map((place, index) => (
        <PlaceCard
          key={place.place_id}
          place={place}
          rank={index + 1}
          variant="panel"
          translations={translations}
        />
      ))}
    </div>
  );

  return (
    <>
      <aside
        className="hidden h-full min-h-0 w-[360px] shrink-0 flex-col border-l border-[#e9e9e7] bg-white lg:flex"
        aria-label={translations.placeResultsHeading}
      >
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-[#e9e9e7] px-5">
          <BadgeCheck className="size-4 text-[#2eaadc]" />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#37352f]">
            {translations.placeResultsHeading}
          </h2>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">{cards}</div>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 bg-black/25 lg:hidden" role="dialog" aria-modal="true" aria-label={translations.placeResultsHeading}>
          <aside className="ml-auto flex h-full w-[min(92vw,380px)] flex-col bg-white shadow-xl">
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-[#e9e9e7] px-4">
              <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide">
                <BadgeCheck className="size-4 text-[#2eaadc]" />
                {translations.placeResultsHeading}
              </span>
              <button type="button" onClick={onMobileClose} className="rounded p-1.5 hover:bg-[#f7f7f5]" aria-label="Close">
                <X className="size-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">{cards}</div>
          </aside>
        </div>
      )}
    </>
  );
}
