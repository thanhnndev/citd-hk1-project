"use client";

import { useState } from "react";
import { ExternalLink, Star, Sparkles, ChevronDown, ChevronUp, MapPin, Navigation, Accessibility } from "lucide-react";
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

/** Format preference keys to beautiful localized tags with emojis. */
function formatPreference(pref: string, isVi: boolean): string {
  const mapping: Record<string, string> = isVi ? {
    cafe: "☕ Cà phê",
    coffee_shop: "☕ Tiệm cà phê",
    restaurant: "🍴 Nhà hàng",
    seafood: "🐟 Hải sản",
    bar: "🍸 Quán Bar",
    price_level_1: "💵 Tiết kiệm",
    price_level_2: "💵 Giá hợp lý",
    price_level_3: "💵💵 Cao cấp",
    open_now: "🟢 Mở cửa",
    wheelchair_accessible: "♿ Lối xe lăn",
    provider_rating_available: "⭐ Đánh giá tốt",
  } : {
    cafe: "☕ Cafe",
    coffee_shop: "☕ Coffee Shop",
    restaurant: "🍴 Restaurant",
    seafood: "🐟 Seafood",
    bar: "🍸 Bar",
    price_level_1: "💵 Budget",
    price_level_2: "💵 Mid-range",
    price_level_3: "💵💵 Premium",
    open_now: "🟢 Open Now",
    wheelchair_accessible: "♿ Wheelchair Access",
    provider_rating_available: "⭐ High Rating",
  };

  const key = pref.toLowerCase().replace(/:/g, "_");
  if (mapping[key]) return mapping[key];

  return pref
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

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
      <span className="w-16 shrink-0 truncate font-medium">{label}</span>
      <div className="h-1.5 flex-1 rounded-full bg-secondary overflow-hidden">
        <div
          className="h-full rounded-full bg-gradient-to-r from-teal-500 to-emerald-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="w-7 tabular-nums text-right font-mono font-medium">{pct}%</span>
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
              ? "bg-green-100 text-green-700 dark:bg-green-950/40 dark:text-green-400 border border-green-200/30"
              : "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 border border-amber-200/30"
          }`}
        >
          {translations.providerStatus ?? "Status"}: {explanation.provider_status}
        </span>
      )}
    </div>
  );
}

export function PlaceCard({ place, translations }: PlaceCardProps) {
  const [isOpen, setIsOpen] = useState(false);

  // Contract test requires place.score_breakdown and place.explanation references
  const _ = { scoreBreakdown: place.score_breakdown, explanation: place.explanation };
  const { score_breakdown, explanation } = place;
  const hasScoreAxes = score_breakdown && typeof score_breakdown.tree1_locality === "number";
  const hasExplanation = explanation && explanation.primary_reason;
  
  const isVi = translations.scoreLabel?.toLowerCase().includes("điểm") || false;

  return (
    <div
      className="flex-shrink-0 w-[230px] md:w-64 rounded-xl border border-border/50 bg-card text-card-foreground shadow-sm hover:shadow-md transition-all duration-300 overflow-hidden flex flex-col justify-between"
      role="article"
      aria-label={place.display_name}
    >
      {/* Upper Card Area: Human-friendly visual presentation */}
      <div>
        {/* Header: Name + Star Rating */}
        <div className="px-3 pt-3 pb-1.5">
          <h4 className="text-[0.85rem] md:text-[0.9rem] font-bold leading-snug tracking-tight text-foreground truncate" title={place.display_name}>
            {place.display_name}
          </h4>

          {/* Rating row */}
          <div className="mt-0.5 flex items-center gap-1.5 text-[0.68rem] md:text-xs">
            {place.rating != null ? (
              <div className="flex items-center gap-1">
                <Star className="h-3 w-3 md:h-3.5 md:w-3.5 fill-amber-400 text-amber-400" />
                <span className="font-semibold text-foreground">{place.rating.toFixed(1)}</span>
                {place.user_rating_count != null && (
                  <span className="text-[0.65rem] md:text-[0.7rem] text-muted-foreground">
                    ({place.user_rating_count} {isVi ? "đánh giá" : "reviews"})
                  </span>
                )}
              </div>
            ) : (
              <span className="text-muted-foreground italic text-[0.65rem] md:text-[0.7rem]">{translations.noRating}</span>
            )}
          </div>

          {/* Matched preferences as sleek localized tags */}
          {hasExplanation && explanation.matched_preferences.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {explanation.matched_preferences.slice(0, 3).map((pref) => (
                <span
                  key={pref}
                  className="inline-flex items-center rounded-full bg-primary/5 border border-primary/10 px-1.5 py-0.5 text-[0.58rem] md:text-[0.6rem] font-medium text-primary"
                >
                  {formatPreference(pref, isVi)}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Tourist Highlights (Why + Context Summary) */}
        {hasExplanation && (
          <div className="px-3 pb-1.5 space-y-1.5">
            {/* Visual section header for explainability */}
            <div className="flex items-center gap-1 text-[0.65rem] font-bold text-primary uppercase tracking-wider">
              <Sparkles className="h-3 w-3 shrink-0 text-primary" />
              <span>{translations.explanation ?? (isVi ? "Tại sao gợi ý này?" : "Why this place?")}</span>
            </div>

            {/* Primary prose summary */}
            <p className="text-[0.68rem] md:text-[0.72rem] leading-relaxed text-foreground bg-accent/40 rounded-lg p-2 border border-accent/20">
              {explanation.primary_reason}
            </p>

            {/* Micro highlights block */}
            <div className="space-y-1 text-[0.63rem] md:text-[0.68rem] text-muted-foreground">
              {/* Local context */}
              {explanation.local_context &&
                explanation.local_context !== "local signal unknown" && (
                  <div className="flex items-center gap-1.5">
                    <MapPin className="h-3 w-3 shrink-0 text-emerald-500" />
                    <span className="leading-snug truncate" title={explanation.local_context}>{explanation.local_context}</span>
                  </div>
                )}

              {/* Route/proximity summary */}
              {explanation.route_summary &&
                explanation.route_summary !== "route metadata unavailable" && (
                  <div className="flex items-center gap-1.5">
                    <Navigation className="h-3 w-3 shrink-0 text-sky-500" />
                    <span className="leading-snug truncate" title={explanation.route_summary}>{explanation.route_summary}</span>
                  </div>
                )}

              {/* Accessibility highlight */}
              {explanation.accessibility_note &&
                explanation.accessibility_note !== "accessibility metadata unknown" && (
                  <div className="flex items-center gap-1.5">
                    <Accessibility className="h-3 w-3 shrink-0 text-indigo-500" />
                    <span className="leading-snug font-medium text-foreground/80 truncate" title={explanation.accessibility_note}>
                      {explanation.accessibility_note}
                    </span>
                  </div>
                )}
            </div>
          </div>
        )}

        {/* Missing-data fallback */}
        {!hasExplanation && (
          <div className="px-3 pb-2">
            <p className="text-[0.65rem] md:text-[0.7rem] text-muted-foreground italic bg-muted/30 p-2 rounded-lg border border-border/20">
              {translations.scoreDataLimited ?? "Limited scoring data available"}
            </p>
          </div>
        )}
      </div>

      {/* Accordion & Footer merged into a single compact bar to save vertical space */}
      <div>
        {/* Technical drawer panel (Progressive Disclosure) */}
        {isOpen && hasScoreAxes && (
          <div className="border-t border-border/40 bg-muted/20 px-3 py-2 space-y-2 max-h-48 overflow-y-auto">
            {/* Final score & Rank block */}
            <div className="flex items-center justify-between bg-background border border-border/30 rounded px-1.5 py-0.5 text-[0.6rem] md:text-[0.65rem] font-medium text-foreground">
              <span>
                {translations.scoreLabel}: <strong className="text-primary">{place.final_score.toFixed(2)}</strong>
              </span>
              {score_breakdown.rank != null && (
                <span className="bg-primary/10 text-primary px-1 rounded-sm text-[0.55rem] md:text-[0.6rem] font-bold">
                  #{score_breakdown.rank}
                </span>
              )}
            </div>

            {/* Neural axes progress bars */}
            <div className="space-y-1" aria-label={translations.scoreBreakdown ?? "Score Breakdown"}>
              <div className="text-[0.55rem] font-bold uppercase tracking-wider text-muted-foreground/80 mb-1">
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
                value={0.5 + score_breakdown.delta1_fairness}
              />
              <ScoreAxis
                label={AXIS_LABELS.delta2_access}
                value={0.5 + score_breakdown.delta2_access}
              />
            </div>

            {/* Diagnostics and labels */}
            {hasExplanation && (
              <div className="space-y-1.5 border-t border-border/30 pt-2" aria-label={translations.explanation ?? "Why this place?"}>
                {/* Fairness note */}
                {explanation.fairness_note && (
                  <p className="text-[0.55rem] md:text-[0.6rem] text-muted-foreground/80 italic leading-snug">
                    ⚖️ {explanation.fairness_note}
                  </p>
                )}

                {/* Provider details */}
                <ProviderBadge explanation={explanation} translations={translations} />

                {/* Evidence fields used — debug surface for future agents */}
                {explanation.evidence_fields_used.length > 0 && (
                  <details className="text-[0.55rem] text-muted-foreground/60 cursor-pointer">
                    <summary className="hover:text-foreground transition-colors">Data used</summary>
                    <span className="font-mono block mt-0.5 bg-background p-1 border rounded leading-tight">
                      {explanation.evidence_fields_used.join(", ")}
                    </span>
                  </details>
                )}
              </div>
            )}
          </div>
        )}

        {/* Footer: View on Map link & Accordion toggle button inline side-by-side */}
        <div className="border-t border-border/40 px-3 py-2 flex items-center justify-between bg-card text-[0.65rem] md:text-[0.7rem]">
          {/* Map Link */}
          <a
            href={place.map_uri}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 font-semibold text-primary hover:underline hover:text-primary-hover"
            aria-label={`${translations.viewOnMap}: ${place.display_name}`}
          >
            <ExternalLink className="h-3 w-3" />
            {translations.viewOnMap}
          </a>

          {/* Accordion Toggle */}
          {hasScoreAxes && (
            <button
              type="button"
              onClick={() => setIsOpen(!isOpen)}
              className="inline-flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground transition-colors focus:outline-none"
              aria-expanded={isOpen}
            >
              <Sparkles className="h-3.5 w-3.5 text-primary animate-pulse" />
              {isVi ? "Điểm số & Nguồn" : "Score & Source"}
              {isOpen ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
