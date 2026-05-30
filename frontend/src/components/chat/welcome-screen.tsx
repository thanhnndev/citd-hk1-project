"use client";

import { Compass, Sparkles, Waves } from "lucide-react";
import { Button } from "@/components/ui/button";

interface WelcomeScreenProps {
  onPromptClick: (prompt: string) => void;
  translations: {
    greeting: string;
    subtitle: string;
    promptChips: string[];
    badgeLabel?: string;
  };
}

export function WelcomeScreen({ onPromptClick, translations }: WelcomeScreenProps) {
  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-3 text-center animate-fadeIn">
      <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/75 px-3 py-1 text-xs font-medium text-primary shadow-sm backdrop-blur">
        <Waves className="size-3.5" />
        {translations.badgeLabel ?? "Local AI travel guide"}
      </div>

      <div className="relative mb-6 flex size-20 items-center justify-center rounded-[2rem] bg-gradient-to-br from-[#0b5f63] via-[#168f8b] to-[#f2a65a] text-white shadow-xl shadow-teal-900/18">
        <Compass className="size-9" />
        <Sparkles className="absolute -right-1 -top-1 size-5 rounded-full bg-white p-1 text-[#c46b22] shadow" />
      </div>

      <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
        {translations.greeting}
      </h2>
      <p className="mt-4 max-w-xl text-base leading-8 text-muted-foreground">
        {translations.subtitle}
      </p>

      <div className="mt-8 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
        {translations.promptChips.map((prompt) => (
          <Button
            key={prompt}
            variant="outline"
            size="sm"
            className="h-auto justify-start rounded-2xl border-white/70 bg-white/70 px-4 py-3 text-left text-xs leading-relaxed shadow-sm backdrop-blur hover:-translate-y-0.5 hover:bg-white hover:shadow-md"
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
