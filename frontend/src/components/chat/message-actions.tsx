"use client";

import { useState, useCallback } from "react";
import { Copy, Check, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MessageActionsProps {
  content: string;
  onRetry?: () => void;
  translations?: {
    copy?: string;
    copied?: string;
    retry?: string;
  };
}

export function MessageActions({ content, onRetry, translations }: MessageActionsProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API may not be available in all contexts
    }
  }, [content]);

  return (
    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
      <Button
        variant="ghost"
        size="icon"
        className="size-7 text-muted-foreground hover:text-foreground"
        onClick={handleCopy}
        aria-label={copied ? translations?.copied ?? "Copied!" : translations?.copy ?? "Copy"}
      >
        {copied ? (
          <Check className="size-3.5 text-green-600" />
        ) : (
          <Copy className="size-3.5" />
        )}
      </Button>

      {onRetry && (
        <Button
          variant="ghost"
          size="icon"
          className="size-7 text-muted-foreground hover:text-foreground"
          onClick={onRetry}
          aria-label={translations?.retry ?? "Retry"}
        >
          <RotateCcw className="size-3.5" />
        </Button>
      )}
    </div>
  );
}
