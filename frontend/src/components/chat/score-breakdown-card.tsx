"use client";

import { BarChart, ChevronDown, ChevronRight, Check, X } from "lucide-react";
import { useState } from "react";
import type { ScoreBreakdown } from "@/lib/chat-api";

interface ScoreBreakdownCardProps {
  breakdown: ScoreBreakdown;
  displayName?: string;
  rank?: number;
  locale?: string;
}

/**
 * ScoreBreakdownCard — Bar chart showing each feature's contribution to
 * the FinalScore (EXP-03).
 */
export function ScoreBreakdownCard({
  breakdown,
  displayName,
  rank,
  locale,
}: ScoreBreakdownCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const lang = (locale === "en" ? "en" : "vi") as "vi" | "en";

  const features = [
    { 
      key: "relevance" as const, 
      label: lang === "vi" ? "Độ liên quan" : "Relevance",
      desc: lang === "vi" ? "Mức độ khớp từ khóa/danh mục với yêu cầu" : "Keyword/category relevance matching user query"
    },
    { 
      key: "proximity" as const, 
      label: lang === "vi" ? "Khoảng cách" : "Proximity",
      desc: lang === "vi" ? "Độ gần vị trí hiện tại hoặc trung tâm xã" : "Proximity to user location or commune center"
    },
    { 
      key: "quality" as const, 
      label: lang === "vi" ? "Chất lượng" : "Quality & Rating",
      desc: lang === "vi" ? "Độ uy tín dựa trên điểm đánh giá trung bình" : "Vendor quality score normalized from ratings"
    },
    { 
      key: "geo_locality" as const, 
      label: lang === "vi" ? "Tính bản địa" : "Geo-locality",
      desc: lang === "vi" ? "Tọa độ nằm trong ranh giới địa phương Hàm Ninh" : "Coordinates within Ham Ninh commune boundary"
    },
    { 
      key: "popularity_damping" as const, 
      label: lang === "vi" ? "Khử thiên vị độ phổ biến (trừ)" : "Popularity debias (subtracted)",
      desc: lang === "vi" ? "Số trừ để giảm bớt ưu thế của chuỗi lớn" : "Subtracted to reduce excessive advantage of large chains"
    },
  ];

  return (
    <div className="mt-2.5 overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50/30">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-800"
        aria-expanded={isOpen}
        aria-controls={`score-breakdown-${displayName ?? "unknown"}`}
      >
        <BarChart className="h-3.5 w-3.5 text-sky-600" />
        <span className="font-semibold text-slate-700">
          {displayName ?? "Địa điểm"}
          {rank !== undefined ? ` #${rank}` : ""}
          <span className="ml-2 font-mono text-[10px] bg-slate-100 px-1.5 py-0.5 rounded text-slate-500">
            {lang === "vi" ? "Điểm số" : "Score"}: {breakdown.final_score.toFixed(3)}
          </span>
        </span>
        <span className="ml-auto transition-transform duration-200">
          {isOpen ? (
            <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 text-slate-400" />
          )}
        </span>
      </button>

      {isOpen && (
        <div
          id={`score-breakdown-${displayName ?? "unknown"}`}
          className="border-t border-slate-200/80 bg-white px-4 py-3.5"
        >
          {/* Gate status indicator */}
          <div className="mb-3 flex items-center justify-between border-b border-slate-100 pb-2.5">
            <span className="text-xs font-medium text-slate-500">
              {lang === "vi" ? "Điều kiện tối thiểu (Relevance Gate)" : "Relevance & Quality Gate"}
            </span>
            <div className="flex items-center gap-1.5">
              {breakdown.gate_passed ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700 ring-1 ring-emerald-600/10">
                  <Check className="size-3" />
                  {lang === "vi" ? "Đạt chuẩn" : "Passed"}
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-bold text-rose-700 ring-1 ring-rose-600/10">
                  <X className="size-3" />
                  {lang === "vi" ? "Chưa đạt" : "Gated (Xếp sau)"}
                </span>
              )}
            </div>
          </div>

          <dl className="space-y-3">
            {features.map((feature) => {
              const isDamping = feature.key === "popularity_damping";
              const value = Number(breakdown[feature.key] ?? 0);
              
              // Weights description
              const weight = breakdown.weights?.[feature.key] || 0;
              const weightStr = isDamping ? "" : ` (w = ${weight.toFixed(2)})`;

              // Percentage for bar width
              const pct = Math.max(0, Math.min(100, value * 100));
              
              const barColor = isDamping
                ? "bg-amber-400"
                : pct >= 70
                  ? "bg-emerald-500"
                  : pct >= 50
                    ? "bg-teal-500"
                    : pct >= 30
                      ? "bg-sky-400"
                      : "bg-slate-400";

              return (
                <div key={feature.key} className="space-y-1">
                  <dt className="flex justify-between text-xs">
                    <div className="flex flex-col">
                      <span className="font-semibold text-slate-700">
                        {feature.label}{weightStr}
                      </span>
                      <span className="text-[10px] text-slate-400 font-normal leading-normal">
                        {feature.desc}
                      </span>
                    </div>
                    <span className={`font-mono font-bold mt-0.5 ${isDamping && value > 0 ? "text-amber-600" : "text-slate-700"}`}>
                      {isDamping ? `-${value.toFixed(3)}` : value.toFixed(3)}
                    </span>
                  </dt>
                  <dd>
                    <div className="h-2 w-full bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-300 ${barColor}`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>
      )}
    </div>
  );
}

