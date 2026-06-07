"use client";

import { ExternalLink, FileText } from "lucide-react";
import type { Citation } from "@/lib/chat-api";

interface CitationCardProps {
  citation: Citation;
  index?: number;
}

export function CitationCard({ citation, index = 1 }: CitationCardProps) {
  const { source, url, snippet } = citation;

  return (
    <div className="max-w-full overflow-hidden rounded-md border border-[#e9e9e7] bg-white px-3 py-2">
      <div className="flex items-start gap-3">
        <div className="grid size-6 shrink-0 place-items-center rounded bg-[#f7f7f5] text-[0.68rem] font-bold text-[#2383e2]">
          {index}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FileText className="size-3.5 shrink-0 text-[#787774]" />
            <p className="min-w-0 truncate text-xs font-medium text-[#37352f]" title={source}>{source}</p>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto rounded p-1 text-[#787774] transition-colors hover:bg-[#f7f7f5] hover:text-[#2383e2]"
                aria-label={`Open source: ${source}`}
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
          {snippet && (
            <p className="mt-1 line-clamp-2 text-[11px] leading-5 text-[#787774]">{snippet}</p>
          )}
        </div>
      </div>
    </div>
  );
}
