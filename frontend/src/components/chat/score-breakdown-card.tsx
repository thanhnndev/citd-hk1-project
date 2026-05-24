"use client";

import { BarChart, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { ScoreBreakdown } from "@/lib/chat-api";

interface ScoreBreakdownCardProps {
  breakdown: ScoreBreakdown;
  displayName?: string;
  rank?: number;
}

/**
 * ScoreBreakdownCard — Bar chart showing each feature's contribution to
 * the FinalScore (EXP-03).
 *
 * Renders the 8 scoring dimensions as horizontal bars with percentage labels.
 * Collapsible to save vertical space in the chat interface.
 */
export function ScoreBreakdownCard({
  breakdown,
  displayName,
  rank,
}: ScoreBreakdownCardProps) {
  const [isOpen, setIsOpen] = useState(false);

  const features: { key: keyof ScoreBreakdown; label: string }[] = [
    { key: "tree1_locality", label: "Locality (Cây 1)" },
    { key: "tree2_proximity", label: "Proximity (Cây 2)" },
    { key: "tree3_quality", label: "Quality (Cây 3)" },
    { key: "s_bag", label: "Bagging (S_BAG)" },
    { key: "delta1_fairness", label: "Fairness Δ1" },
    { key: "delta2_access", label: "Access Δ2" },
  ];

  return (
    <div className="mt-2 border border-border/40 rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        aria-expanded={isOpen}
        aria-controls={`score-breakdown-${displayName ?? "unknown"}`}
      >
        <BarChart className="h-3.5 w-3.5 text-blue-500" />
        <span className="font-medium">
          {displayName ?? "Place"}
          {rank !== undefined ? ` — Rank #${rank}` : ""}
          <span className="ml-2 text-xs font-normal">
            Score: {breakdown.final_score.toFixed(3)}
          </span>
        </span>
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
          id={`score-breakdown-${displayName ?? "unknown"}`}
          className="border-t border-border/40 bg-muted/30 px-3 py-3"
        >
          <dl className="space-y-2">
            {features.map((feature) => {
              const value = Number(breakdown[feature.key] ?? 0);
              const pct = Math.max(0, Math.min(100, value * 100));
              const barColor =
                pct >= 70
                  ? "bg-emerald-500"
                  : pct >= 50
                    ? "bg-amber-500"
                    : pct >= 30
                      ? "bg-orange-400"
                      : "bg-red-400";

              return (
                <div key={feature.key} className="space-y-0.5">
                  <dt className="flex justify-between text-xs">
                    <span className="text-muted-foreground">
                      {feature.label}
                    </span>
                    <span className="font-mono">{value.toFixed(3)}</span>
                  </dt>
                  <dd>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
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
