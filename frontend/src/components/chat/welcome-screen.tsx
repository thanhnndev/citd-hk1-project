"use client";

import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

interface WelcomeScreenProps {
  onPromptClick: (prompt: string) => void;
  translations: {
    greeting: string;
    subtitle: string;
    promptChips: string[];
  };
}

export function WelcomeScreen({ onPromptClick, translations }: WelcomeScreenProps) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center animate-fadeIn">
      <div className="mb-6 flex size-16 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Sparkles className="size-8" />
      </div>

      <h2 className="text-2xl font-semibold text-foreground">{translations.greeting}</h2>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
        {translations.subtitle}
      </p>

      <div className="mt-8 flex flex-wrap justify-center gap-2 max-w-xl">
        {translations.promptChips.map((prompt) => (
          <Button
            key={prompt}
            variant="outline"
            size="sm"
            className="rounded-full border-muted-foreground/20 hover:bg-muted text-xs"
            onClick={() => onPromptClick(prompt)}
            aria-label={`Ask: ${prompt}`}
          >
            {prompt}
          </Button>
        ))}
      </div>
    </div>
  );
}
