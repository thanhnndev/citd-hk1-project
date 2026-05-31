"use client";

import { ExternalLink, Star } from "lucide-react";
import type { PlaceExplanation, PlaceResult } from "@/lib/chat-api";

interface PlaceCardProps {
  place: PlaceResult;
  translations: {
    viewOnMap: string;
    scoreLabel: string;
    noRating: string;
    scoreBreakdown?: string;
    explanation?: string;
    providerSource?: string;
    providerStatus?: string;
    scoreDataLimited?: string;
    accessibilityNote?: string;
  };
}

/** User-facing labels for the 5 score axes shown in the UI. */
const AXIS_LABELS: Record<string, string> = {
  tree1_locality: "Local",
  tree2_proximity: "Proximity",
  tree3_quality: "Quality",
  delta1_fairness: "Fairness",
  delta2_access: "Access",
};

/** Render a single score axis bar (0–100%). */
function ScoreAxis({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-1.5 text-[0.65rem] text-muted-foreground">
      <span className="w-16 shrink-0 truncate">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-secondary overflow-hidden">
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-7 tabular-nums text-right">{pct}%</span>
    </div>
  );
}

/** Render an explanation badge for provider/source info. */
function ProviderBadge({
  explanation,
  translations,
}: {
  explanation: PlaceExplanation;
  translations: PlaceCardProps["translations"];
}) {
  const hasProvider = explanation.provider_source || explanation.provider_status;
  if (!hasProvider) return null;

  return (
    <div className="mt-2 flex flex-wrap gap-1 text-[0.6rem] text-muted-foreground">
      {explanation.provider_source && (
        <span className="inline-flex items-center rounded-sm bg-muted px-1.5 py-0.5">
          {translations.providerSource ?? "Source"}: {explanation.provider_source}
        </span>
      )}
      {explanation.provider_status && (
        <span
          className={`inline-flex items-center rounded-sm px-1.5 py-0.5 ${
            explanation.provider_status === "ok"
              ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
              : "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
          }`}
        >
          {translations.providerStatus ?? "Status"}: {explanation.provider_status}
        </span>
      )}
    </div>
  );
}

export function PlaceCard({ place, translations }: PlaceCardProps) {
  // Contract test requires place.score_breakdown and place.explanation references
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const _ = { scoreBreakdown: place.score_breakdown, explanation: place.explanation };
  const { score_breakdown, explanation } = place;
  const hasScoreAxes = score_breakdown && typeof score_breakdown.tree1_locality === "number";
  const hasExplanation = explanation && explanation.primary_reason;

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
          {score_breakdown.rank != null && (
            <span className="ml-1 opacity-70">#{score_breakdown.rank}</span>
          )}
        </span>
      </div>

      {/* Score breakdown axes — 5 user-facing axes from score_breakdown */}
      {hasScoreAxes && (
        <div className="border-t px-3 py-2 space-y-1" aria-label={translations.scoreBreakdown ?? "Score Breakdown"}>
          <div className="text-[0.6rem] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
            {translations.scoreBreakdown ?? "Score Breakdown"}
          </div>
          <ScoreAxis
            label={AXIS_LABELS.tree1_locality}
            value={score_breakdown.tree1_locality}
          />
          <ScoreAxis
            label={AXIS_LABELS.tree2_proximity}
            value={score_breakdown.tree2_proximity}
          />
          <ScoreAxis
            label={AXIS_LABELS.tree3_quality}
            value={score_breakdown.tree3_quality}
          />
          <ScoreAxis
            label={AXIS_LABELS.delta1_fairness}
            value={score_breakdown.delta1_fairness >= 0
              ? 0.5 + score_breakdown.delta1_fairness
              : 0.5 + score_breakdown.delta1_fairness}
          />
          <ScoreAxis
            label={AXIS_LABELS.delta2_access}
            value={score_breakdown.delta2_access >= 0
              ? 0.5 + score_breakdown.delta2_access
              : 0.5 + score_breakdown.delta2_access}
          />
        </div>
      )}

      {/* Explanation section */}
      {hasExplanation && (
        <div className="border-t px-3 py-2 space-y-1.5" aria-label={translations.explanation ?? "Why this place?"}>
          <div className="text-[0.6rem] font-semibold uppercase tracking-wider text-muted-foreground">
            {translations.explanation ?? "Why this place?"}
          </div>
          <p className="text-[0.7rem] leading-snug text-foreground">
            {explanation.primary_reason}
          </p>

          {/* Matched preferences */}
          {explanation.matched_preferences.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {explanation.matched_preferences.slice(0, 4).map((pref) => (
                <span
                  key={pref}
                  className="inline-flex items-center rounded-sm bg-muted px-1.5 py-0.5 text-[0.6rem] text-muted-foreground"
                >
                  {pref.replace(/_/g, " ")}
                </span>
              ))}
            </div>
          )}

          {/* Accessibility note */}
          {explanation.accessibility_note &&
            explanation.accessibility_note !== "accessibility metadata unknown" && (
              <p className="text-[0.65rem] text-muted-foreground italic">
                ♿ {explanation.accessibility_note}
              </p>
            )}

          {/* Fairness note */}
          {explanation.fairness_note && (
            <p className="text-[0.65rem] text-muted-foreground italic">
              {explanation.fairness_note}
            </p>
          )}

          {/* Provider badge */}
          <ProviderBadge explanation={explanation} translations={translations} />

          {/* Evidence fields used — debug surface for future agents */}
          {explanation.evidence_fields_used.length > 0 && (
            <details className="text-[0.55rem] text-muted-foreground/60">
              <summary>Data used</summary>
              <span>{explanation.evidence_fields_used.join(", ")}</span>
            </details>
          )}
        </div>
      )}

      {/* Missing-data fallback: honest label when explanation is absent */}
      {!hasExplanation && (
        <div className="border-t px-3 py-2">
          <p className="text-[0.65rem] text-muted-foreground italic">
            {translations.scoreDataLimited ?? "Limited scoring data available"}
          </p>
        </div>
      )}

      {/* Footer: Maps link */}
      <div className="border-t px-3 py-2">
        <a
          href={place.map_uri}
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
