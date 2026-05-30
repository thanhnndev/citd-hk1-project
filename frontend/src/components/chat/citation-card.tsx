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
    <div className="max-w-full overflow-hidden rounded-xl border border-[#0b5f63]/10 bg-[#fffdf8] p-3 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="grid size-7 shrink-0 place-items-center rounded-lg bg-[#0b5f63]/10 text-[0.72rem] font-bold text-[#0b5f63]">
          {index}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <FileText className="size-3.5 shrink-0 text-[#0b5f63]" />
            <p className="min-w-0 truncate text-sm font-semibold text-[#173a3b]" title={source}>{source}</p>
            {url && (
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto rounded-full p-1 text-[#6b7f7e] transition-colors hover:bg-[#0b5f63]/10 hover:text-[#0b5f63]"
                aria-label={`Open source: ${source}`}
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
          {snippet && (
            <p className="mt-1 line-clamp-2 text-xs leading-5 text-[#5d7373]">{snippet}</p>
          )}
        </div>
      </div>
    </div>
  );
}
