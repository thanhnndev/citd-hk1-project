"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ExternalLink } from "lucide-react";
import type { Citation } from "@/lib/chat-api";

interface CitationCardProps {
  citation: Citation;
}

export function CitationCard({ citation }: CitationCardProps) {
  const { source, url, snippet } = citation;

  return (
    <Card className="border-l-4 border-l-primary/30">
      <CardContent className="pt-4">
        <div className="flex items-center gap-2 mb-2">
          <Badge variant="secondary">{source}</Badge>
          {url && (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-primary transition-colors"
              aria-label={`Open source: ${source}`}
            >
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
        {snippet && (
          <p className="text-sm text-muted-foreground line-clamp-3">{snippet}</p>
        )}
      </CardContent>
    </Card>
  );
}
