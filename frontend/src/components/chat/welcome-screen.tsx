"use client";

import { BookOpenText, Compass, MapPinned, Route, Sparkles, Utensils, Waves } from "lucide-react";
import { Button } from "@/components/ui/button";

interface WelcomeIntent {
  title: string;
  description: string;
  badge: string;
  prompts: string[];
}

interface WelcomeScreenProps {
  onPromptClick: (prompt: string) => void;
  translations: {
    greeting: string;
    subtitle: string;
    promptChips: string[];
    badgeLabel?: string;
    disclosure?: string;
    quickPromptLabel?: string;
    guidanceCards?: { title: string; body: string }[];
    welcomeIntents?: WelcomeIntent[];
  };
}

const ICONS = [BookOpenText, Utensils, Route, MapPinned];

export function WelcomeScreen({ onPromptClick, translations }: WelcomeScreenProps) {
  const intents = translations.welcomeIntents ?? translations.guidanceCards?.map((card, index) => ({
    title: card.title,
    description: card.body,
    badge: translations.quickPromptLabel ?? "Try",
    prompts: translations.promptChips[index] ? [translations.promptChips[index]] : [],
  })) ?? translations.promptChips.map((prompt, index) => ({
    title: prompt,
    description: translations.subtitle,
    badge: translations.quickPromptLabel ?? "Try",
    prompts: [prompt],
  }));

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col items-center justify-center px-3 py-5 text-center animate-fadeIn">
      <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/70 bg-white/75 px-3 py-1 text-xs font-medium text-primary shadow-sm backdrop-blur">
        <Waves className="size-3.5" />
        {translations.badgeLabel ?? "Local AI travel guide"}
      </div>

      <div className="relative mb-5 flex size-16 items-center justify-center rounded-[1.6rem] bg-gradient-to-br from-[#0b5f63] via-[#168f8b] to-[#f2a65a] text-white shadow-xl shadow-teal-900/18 md:size-20 md:rounded-[2rem]">
        <Compass className="size-8 md:size-9" />
        <Sparkles className="absolute -right-1 -top-1 size-5 rounded-full bg-white p-1 text-[#c46b22] shadow" />
      </div>

      <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
        {translations.greeting}
      </h2>
      <p className="mt-4 max-w-2xl text-base leading-8 text-muted-foreground">
        {translations.subtitle}
      </p>

      <div className="mt-7 flex items-center gap-2 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-[#0b5f63]">
        <Sparkles className="size-3.5" />
        <span>{translations.quickPromptLabel ?? "Choose a starting point"}</span>
      </div>

      <div className="mt-3 grid w-full gap-3 text-left sm:grid-cols-2">
        {intents.slice(0, 4).map((intent, index) => {
          const Icon = ICONS[index % ICONS.length];
          return (
            <section
              key={`${intent.title}-${index}`}
              className="group rounded-[1.4rem] border border-white/75 bg-white/72 p-4 shadow-sm backdrop-blur transition duration-200 hover:-translate-y-0.5 hover:bg-white hover:shadow-lg hover:shadow-[#0b5f63]/10"
            >
              <div className="flex items-start gap-3">
                <div className="grid size-10 shrink-0 place-items-center rounded-2xl bg-[#0b5f63]/10 text-[#0b5f63] transition group-hover:bg-[#0b5f63] group-hover:text-white">
                  <Icon className="size-5" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-sm font-semibold text-[#123436]">{intent.title}</h3>
                    <span className="rounded-full bg-[#f2a65a]/18 px-2 py-0.5 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-[#9a581f]">
                      {intent.badge}
                    </span>
                  </div>
                  <p className="mt-1 text-xs leading-5 text-[#5d7373]">{intent.description}</p>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={intent.title}>
                {intent.prompts.slice(0, 2).map((prompt) => (
                  <Button
                    key={prompt}
                    variant="outline"
                    size="sm"
                    className="h-auto rounded-full border-[#0b5f63]/18 bg-white/78 px-3 py-1.5 text-left text-xs leading-relaxed text-[#0b5f63] shadow-sm hover:bg-[#0b5f63]/10"
                    onClick={() => onPromptClick(prompt)}
                    aria-label={`Ask: ${prompt}`}
                  >
                    {prompt}
                  </Button>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <p className="mt-5 max-w-2xl rounded-2xl border border-[#0b5f63]/10 bg-white/65 px-4 py-3 text-xs leading-5 text-[#5d7373] shadow-sm">
        {translations.disclosure ?? "AI assistant: verify important route, opening-hour, and safety details with a map or official source."}
      </p>
    </div>
  );
}
