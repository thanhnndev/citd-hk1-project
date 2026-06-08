"use client";

import { ChevronDown, ChevronRight, Lightbulb } from "lucide-react";
import { useState } from "react";

interface ReasoningLogProps {
  reasoningLog: string;
  label?: string;
  locale?: string;
}

const KEY_MAP: Record<"vi" | "en", Record<string, string>> = {
  vi: {
    status: "Trạng thái",
    source: "Nguồn dữ liệu",
    candidate_count: "Số địa điểm gốc",
    result_count: "Số địa điểm gợi ý",
    budget_preference: "Bộ lọc ngân sách",
    top5_local_ratio: "Tỉ lệ địa phương Top 5",
    missing_geo_locality: "Không có định vị",
    warnings: "Cảnh báo hệ thống",
    audit_events: "Lịch sử kiểm tra",
    credential_status: "Xác thực dịch vụ",
    log: "Nhật ký hệ thống",
  },
  en: {
    status: "Status",
    source: "Data source",
    candidate_count: "Raw places found",
    result_count: "Places recommended",
    budget_preference: "Budget filter",
    top5_local_ratio: "Local ratio in Top 5",
    missing_geo_locality: "Missing geo-location",
    warnings: "System warnings",
    audit_events: "Audit events",
    credential_status: "Credential status",
    log: "System log",
  }
};

const VALUE_MAP: Record<"vi" | "en", Record<string, string>> = {
  vi: {
    ok: "Thành công",
    empty: "Trống",
    credentials_blocked: "Lỗi cấu hình API",
    upstream_error: "Lỗi kết nối máy chủ",
    unavailable: "Dịch vụ tạm thời gián đoạn",
    google_places: "Google Places API (New)",
    goong_places: "Goong Maps API (Dự phòng)",
    cache: "Bộ nhớ đệm cục bộ (Cache)",
    mock: "Dữ liệu mô phỏng",
    free: "Miễn phí",
    inexpensive: "Giá rẻ",
    moderate: "Bình dân",
    expensive: "Cao cấp",
    very_expensive: "Sang trọng",
    none: "Không",
    passed: "Đạt chuẩn",
    true: "Có",
    false: "Không",
  },
  en: {
    ok: "Success",
    empty: "Empty",
    credentials_blocked: "API credentials blocked",
    upstream_error: "Upstream server error",
    unavailable: "Temporarily unavailable",
    google_places: "Google Places API (New)",
    goong_places: "Goong Maps API (Fallback)",
    cache: "Local cache",
    mock: "Mock database",
    free: "Free",
    inexpensive: "Inexpensive",
    moderate: "Moderate",
    expensive: "Expensive",
    very_expensive: "Very expensive",
    none: "None",
    passed: "Verified",
    true: "Yes",
    false: "No",
  }
};

export function ReasoningLog({ reasoningLog, label, locale }: ReasoningLogProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (!reasoningLog) return null;

  const lang = (locale === "en" ? "en" : "vi") as "vi" | "en";
  const displayLabel = label || (lang === "vi" ? "Cách AI chọn địa điểm này?" : "How did AI select this?");

  // Parse key=value pairs from the reasoning log
  const parseLog = (log: string) => {
    const entries: { key: string; value: string; displayKey: string; displayValue: string }[] = [];
    const regex = /(\w[\w_]*)\s*=\s*([^\s,]+)/g;
    let match;
    while ((match = regex.exec(log)) !== null) {
      const k = match[1];
      const v = match[2];
      const displayKey = KEY_MAP[lang][k] || k;
      
      let displayValue = VALUE_MAP[lang][v] || v;
      if (k === "top5_local_ratio") {
        const pct = parseFloat(v);
        if (!isNaN(pct)) {
          displayValue = `${(pct * 100).toFixed(0)}%`;
        }
      }

      entries.push({ key: k, value: v, displayKey, displayValue });
    }
    
    if (entries.length === 0) {
      return [{ key: "log", value: log, displayKey: KEY_MAP[lang]["log"], displayValue: log }];
    }
    return entries;
  };

  const entries = parseLog(reasoningLog);

  return (
    <div className="mt-2.5 overflow-hidden rounded-xl border border-slate-200/80 bg-slate-50/30">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex w-full items-center gap-2 px-3.5 py-2.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 hover:text-slate-800"
        aria-expanded={isOpen}
        aria-controls="reasoning-log-content"
      >
        <Lightbulb className="h-3.5 w-3.5 text-amber-500 animate-pulse" />
        <span>{displayLabel}</span>
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
          id="reasoning-log-content"
          className="border-t border-slate-200/80 bg-white/70 px-4 py-3"
        >
          <dl className="grid gap-x-4 gap-y-2 grid-cols-2 text-xs">
            {entries.map((entry, index) => (
              <div key={index} className="flex flex-col sm:flex-row sm:justify-between py-1 border-b border-slate-100 last:border-b-0">
                <dt className="font-medium text-slate-500">
                  {entry.displayKey}
                </dt>
                <dd className="font-semibold text-slate-800 sm:text-right mt-0.5 sm:mt-0">
                  {entry.displayValue}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}

