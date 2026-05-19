"use client";

import { ExternalLink, Star } from "lucide-react";
import type { PlaceResult } from "@/lib/chat-api";

interface PlaceCardProps {
  place: PlaceResult;
  translations: {
    viewOnMap: string;
    scoreLabel: string;
    noRating: string;
  };
}

export function PlaceCard({ place, translations }: PlaceCardProps) {
  return (
    <div
      className="flex-shrink-0 w-56 rounded-xl border bg-card text-card-foreground shadow-sm overflow-hidden"
      role="article"
      aria-label={place.display_name}
    >
      {/* Header: name + rating */}
      <div className="px-3 pt-3 pb-2">
        <h4 className="text-sm font-semibold leading-tight truncate" title={place.display_name}>
          {place.display_name}
        </h4>

        {/* Rating row */}
        <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          {place.rating != null ? (
            <>
              <Star className="h-3.5 w-3.5 fill-yellow-400 text-yellow-400" />
              <span>{place.rating.toFixed(1)}</span>
              {place.user_rating_count != null && (
                <span className="opacity-70">({place.user_rating_count})</span>
              )}
            </>
          ) : (
            <span>{translations.noRating}</span>
          )}
        </div>
      </div>

      {/* Score badge */}
      <div className="px-3 pb-2">
        <span className="inline-flex items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
          {translations.scoreLabel}: {place.final_score.toFixed(2)}
        </span>
      </div>

      {/* Footer: Maps link */}
      <div className="border-t px-3 py-2">
        <a
          href={place.google_maps_uri}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          aria-label={`${translations.viewOnMap}: ${place.display_name}`}
        >
          <ExternalLink className="h-3 w-3" />
          {translations.viewOnMap}
        </a>
      </div>
    </div>
  );
}
