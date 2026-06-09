"use client";

import { useMemo, useState } from "react";
import { ExternalLink, MapPin, Star, ChevronDown, ChevronUp, Navigation, Baby, Trees, Utensils } from "lucide-react";
import type { PlaceExplanation, PlaceResult } from "@/lib/chat-api";
import { ScoreBreakdownCard } from "./score-breakdown-card";

export interface PlaceCardTranslations {
  viewOnMap: string;
  scoreLabel: string;
  noRating: string;
  scoreBreakdown?: string;
  explanation?: string;
  providerSource?: string;
  providerStatus?: string;
  scoreDataLimited?: string;
  accessibilityNote?: string;
}

interface PlaceCardProps {
  place: PlaceResult;
  rank?: number;
  variant?: "default" | "panel";
  translations: PlaceCardTranslations;
}

type FriendlyCategory = {
  labelVi: string;
  labelEn: string;
  icon: typeof Baby;
};

const CATEGORY_BY_TYPE: Record<string, FriendlyCategory> = {
  amusement_park: { labelVi: "Khu vui chơi", labelEn: "Play stop", icon: Baby },
  museum: { labelVi: "Trải nghiệm trong nhà", labelEn: "Indoor stop", icon: Baby },
  tourist_attraction: { labelVi: "Điểm tham quan", labelEn: "Sightseeing", icon: Trees },
  park: { labelVi: "Không gian ngoài trời", labelEn: "Outdoor space", icon: Trees },
  restaurant: { labelVi: "Ăn uống", labelEn: "Food stop", icon: Utensils },
  seafood_restaurant: { labelVi: "Ăn hải sản", labelEn: "Seafood stop", icon: Utensils },
  vietnamese_restaurant: { labelVi: "Ăn uống", labelEn: "Food stop", icon: Utensils },
};

const HIDDEN_INTERNAL_PATTERNS = [
  /provider rating available/gi,
  /payments?:\s*[^,.]+[,.]?/gi,
  /parking:\s*[^,.]+[,.]?/gi,
  /accessibility score\s*\d+(\.\d+)?/gi,
  /type label:\s*[^,.]+[,.]?/gi,
];

function cleanReason(text: string | undefined, fallback: string): string {
  if (!text) return fallback;
  let cleaned = text;
  for (const pattern of HIDDEN_INTERNAL_PATTERNS) {
    cleaned = cleaned.replace(pattern, "");
  }
  cleaned = cleaned.replace(/\s+/g, " ").replace(/\s+([,.])/g, "$1").trim();
  if (!cleaned || cleaned.length < 24) return fallback;
  return cleaned;
}

function friendlyType(place: PlaceResult): FriendlyCategory {
  const types = [place.primary_type, ...place.types].filter(Boolean).map((item) => String(item).toLowerCase());
  for (const type of types) {
    if (CATEGORY_BY_TYPE[type]) return CATEGORY_BY_TYPE[type];
  }
  return { labelVi: "Gợi ý ghé thăm", labelEn: "Suggested stop", icon: MapPin };
}

function isVietnamese(translations: PlaceCardProps["translations"]): boolean {
  return translations.scoreLabel?.toLowerCase().includes("điểm") || translations.viewOnMap.toLowerCase().includes("bản đồ");
}

function shortAddress(address?: string | null): string | null {
  if (!address) return null;
  return address.split(",").slice(0, 2).join(",").trim();
}

function hasVerifiedWheelchairAccess(place: PlaceResult): boolean {
  return place.accessibility_score === 1 && !place.accessibility_warning;
}

export function PlaceCard({ place, rank, variant = "default", translations }: PlaceCardProps) {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const isVi = isVietnamese(translations);
  const category = friendlyType(place);
  const CategoryIcon = category.icon;
  const categoryLabel = isVi ? category.labelVi : category.labelEn;
  const address = shortAddress(place.formatted_address);
  const explanation: PlaceExplanation | undefined = place.explanation;
  const reason = useMemo(() => cleanReason(
    explanation?.primary_reason,
    isVi
      ? `${place.display_name} có thể phù hợp nếu bạn cần một điểm dừng dễ sắp xếp trong chuyến đi.`
      : `${place.display_name} may work as an easy stop to fit into the trip.`,
  ), [place.display_name, explanation?.primary_reason, isVi]);
  const highlights = [
    place.open_now === true ? (isVi ? "Đang mở" : "Open now") : null,
    place.rating != null && place.rating >= 4.5 ? (isVi ? "Đánh giá cao" : "Highly rated") : null,
    hasVerifiedWheelchairAccess(place) ? (isVi ? "Có lối vào xe lăn" : "Wheelchair entrance") : null,
    place.price_level != null ? '₫'.repeat(place.price_level) : null,
  ].filter(Boolean) as string[];

  return (
    <article
      className={
        variant === "panel"
          ? "flex flex-col justify-between rounded-xl border border-[#e9e9e7] bg-white p-4 shadow-sm transition hover:border-[#2383e2]/35 hover:shadow-md"
          : "flex min-h-[15rem] flex-col justify-between rounded-3xl border border-[#0b5f63]/12 bg-[#fffdf8] p-4 shadow-sm transition hover:-translate-y-0.5 hover:shadow-lg hover:shadow-[#0b5f63]/10"
      }
      aria-label={place.display_name}
    >
      <div>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              {rank && (
                <span className="grid size-6 place-items-center rounded-full bg-[#0b5f63] text-[0.7rem] font-bold text-white">
                  {rank}
                </span>
              )}
              <span className="inline-flex items-center gap-1 rounded-full bg-[#0b5f63]/8 px-2 py-1 text-[0.68rem] font-semibold text-[#0b5f63]">
                <CategoryIcon className="size-3" />
                {categoryLabel}
              </span>
              {place.score_breakdown?.gate_tier === "low" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-red-50 border border-red-200 px-2 py-1 text-[0.68rem] font-semibold text-red-700">
                  ⚠️ {isVi ? "Chưa đủ dữ liệu, cần người dùng kiểm tra lại" : "Insufficient data, please verify"}
                </span>
              )}
            </div>
            <h4 className="mt-2 line-clamp-2 text-base font-semibold leading-snug text-[#123436]" title={place.display_name}>
              {place.display_name}
            </h4>
          </div>
          {place.rating != null ? (
            <div className="shrink-0 rounded-2xl bg-amber-50 px-2 py-1 text-right text-xs text-amber-800 ring-1 ring-amber-200/70">
              <div className="flex items-center justify-end gap-1 font-bold">
                <Star className="size-3 fill-amber-400 text-amber-400" />
                {place.rating.toFixed(1)}
              </div>
              {place.user_rating_count != null && <div className="text-[0.62rem] opacity-75">{place.user_rating_count}</div>}
            </div>
          ) : null}
        </div>

        {address && (
          <p className="mt-2 flex items-center gap-1.5 text-xs leading-5 text-[#5d7373]">
            <MapPin className="size-3.5 shrink-0 text-[#0b5f63]" />
            <span className="line-clamp-1">{address}</span>
          </p>
        )}

        <p className="mt-3 rounded-2xl bg-[#0b5f63]/6 p-3 text-sm leading-6 text-[#24494b]">
          {reason}
        </p>

        {highlights.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {highlights.slice(0, 3).map((highlight) => (
              <span key={highlight} className="rounded-full border border-[#0b5f63]/12 bg-white px-2 py-1 text-[0.68rem] font-medium text-[#426365]">
                {highlight}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4 border-t border-[#0b5f63]/10 pt-3">
        {detailsOpen && (
          <div className="mb-3 space-y-2 rounded-2xl bg-[#f5efe3] p-3 text-xs leading-5 text-[#426365]">
            {explanation?.route_summary && explanation.route_summary !== "route metadata unavailable" && (
              <p className="flex gap-1.5"><Navigation className="mt-0.5 size-3.5 shrink-0 text-[#0b5f63]" />{explanation.route_summary}</p>
            )}
            {explanation?.local_context && explanation.local_context !== "local signal unknown" && (
              <p>{cleanReason(explanation.local_context, explanation.local_context)}</p>
            )}
            {explanation?.accessibility_note && explanation.accessibility_note !== "accessibility metadata unknown" && (
              <p>{cleanReason(explanation.accessibility_note, explanation.accessibility_note)}</p>
            )}
            {place.accessibility_warning && (
              <p>{place.accessibility_warning}</p>
            )}
            {explanation?.fairness_note && explanation.fairness_note !== "local representation metadata limited" && (
              <p>{cleanReason(explanation.fairness_note, explanation.fairness_note)}</p>
            )}
            {explanation?.detail_highlights?.slice(0, 2).map((item) => (
              <p key={item}>{cleanReason(item, item)}</p>
            ))}
            {place.score_breakdown && (
              <div className="mt-3 text-slate-800">
                <ScoreBreakdownCard
                  breakdown={place.score_breakdown}
                  displayName={place.display_name}
                  rank={rank}
                  locale={isVi ? "vi" : "en"}
                />
              </div>
            )}
            <p className="text-[0.68rem] opacity-75">
              {isVi ? "Nguồn dữ liệu và điểm số giúp giải thích vì sao địa điểm này được ưu tiên." : "Data sources and score details explain why this place was prioritized."}
            </p>
          </div>
        )}
        <div className="flex items-center justify-between gap-2">
          <a
            href={place.map_uri}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-full bg-[#0b5f63] px-3 py-2 text-xs font-semibold text-white shadow-sm hover:bg-[#084d50]"
            aria-label={`${translations.viewOnMap}: ${place.display_name}`}
          >
            <ExternalLink className="size-3.5" />
            {translations.viewOnMap}
          </a>
          <button
            type="button"
            onClick={() => setDetailsOpen((value) => !value)}
            className="inline-flex items-center gap-1 rounded-full px-2 py-2 text-xs font-semibold text-[#0b5f63] hover:bg-[#0b5f63]/8"
            aria-expanded={detailsOpen}
          >
            {isVi ? "Chi tiết" : "Details"}
            {detailsOpen ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
          </button>
        </div>
      </div>
    </article>
  );
}
