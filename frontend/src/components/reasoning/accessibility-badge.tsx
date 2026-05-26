"use client";

import { Badge } from "@/components/ui/badge";
import { Shield, AlertTriangle, Zap, Database, Eye } from "lucide-react";

interface AccessibilityBadgeProps {
  guardrailStatus?: string;
  fallback?: boolean;
  langfuseTraceId?: string | null;
  cacheHit?: boolean;
}

/**
 * Renders colored status badges for chat messages based on guardrail,
 * fallback, tracing, and cache status.
 *
 * Color mapping:
 *   - green  → 'pass' (guardrail passed)
 *   - red    → 'input_blocked' / 'output_flagged' (guardrail blocked)
 *   - yellow → fallback mode active
 *   - blue   → cache hit
 *   - purple → langfuse trace available
 */
export function AccessibilityBadge({
  guardrailStatus,
  fallback,
  langfuseTraceId,
  cacheHit,
}: AccessibilityBadgeProps) {
  const badges: Array<{ label: string; variant: string; icon: React.ReactNode; title: string }> = [];

  // Guardrail status badges
  if (guardrailStatus === "pass") {
    badges.push({
      label: "Guardrail Pass",
      variant: "success",
      icon: <Shield className="h-3 w-3" />,
      title: "Content passed safety guardrails",
    });
  } else if (guardrailStatus === "input_blocked" || guardrailStatus === "output_flagged") {
    badges.push({
      label: guardrailStatus === "input_blocked" ? "Input Blocked" : "Output Flagged",
      variant: "destructive",
      icon: <AlertTriangle className="h-3 w-3" />,
      title: "Content was blocked by safety guardrails",
    });
  }

  // Fallback badge
  if (fallback) {
    badges.push({
      label: "Fallback Mode",
      variant: "outline",
      icon: <Zap className="h-3 w-3" />,
      title: "Response generated using fallback strategy",
    });
  }

  // Cache hit badge
  if (cacheHit) {
    badges.push({
      label: "Cached",
      variant: "outline",
      icon: <Database className="h-3 w-3" />,
      title: "Response served from cache",
    });
  }

  // Langfuse trace badge
  if (langfuseTraceId) {
    badges.push({
      label: "Traced",
      variant: "outline",
      icon: <Eye className="h-3 w-3" />,
      title: `Langfuse trace: ${langfuseTraceId}`,
    });
  }

  if (badges.length === 0) {
    return null;
  }

  return (
    <div className="mt-2 flex flex-wrap gap-1.5" role="status" aria-label="Response status indicators">
      {badges.map((badge) => (
        <Badge
          key={badge.label}
          variant={badge.variant as "success" | "destructive" | "outline"}
          title={badge.title}
          className="text-[10px] leading-tight"
        >
          {badge.icon}
          {badge.label}
        </Badge>
      ))}
    </div>
  );
}
