"use client";

import { ChevronDown, ChevronRight, Lightbulb } from "lucide-react";
import { useState } from "react";

interface ReasoningLogProps {
  reasoningLog: string;
  label?: string;
}

/**
 * ReasoningLog — Accordion "Tại sao gợi ý này?" component (EXP-01).
 *
 * Displays the reasoning_log from AgentState in an expandable accordion.
 * The log contains structured information about retrieval mode, fallback status,
 * citation count, and place recommendation metadata.
 */
export function ReasoningLog({ reasoningLog, label }: ReasoningLogProps) {
  const [isOpen, setIsOpen] = useState(false);

  if (!reasoningLog) return null;

  const displayLabel = label || "Tại sao gợi ý này?";

  // Parse key=value pairs from the reasoning log for structured display
  const parseLog = (log: string) => {
    const entries: { key: string; value: string }[] = [];
    const regex = /(\w[\w_]*)\s*=\s*([^\s,]+)/g;
    let match;
    while ((match = regex.exec(log)) !== null) {
      entries.push({ key: match[1], value: match[2] });
    }
    // If no key=value pairs found, return the raw log
    if (entries.length === 0) {
      return [{ key: "log", value: log }];
    }
    return entries;
  };

  const entries = parseLog(reasoningLog);

  return (
    <div className="mt-2 border border-border/40 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        aria-expanded={isOpen}
        aria-controls="reasoning-log-content"
      >
        <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
        <span className="font-medium">{displayLabel}</span>
        <span className="ml-auto transition-transform duration-200">
          {isOpen ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
        </span>
      </button>

      {isOpen && (
        <div
          id="reasoning-log-content"
          className="border-t border-border/40 bg-muted/30 px-3 py-2"
        >
          <dl className="space-y-1 text-xs">
            {entries.map((entry, index) => (
              <div key={index} className="flex gap-2">
                <dt className="font-mono text-muted-foreground min-w-[140px]">
                  {entry.key}
                </dt>
                <dd className="text-foreground">{entry.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  );
}
