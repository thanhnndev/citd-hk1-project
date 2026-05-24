import { ArrowDown, Boxes, MapPinned } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

type TrustBadge = Readonly<{
  label: string;
  description: string;
}>;

type HeroSectionProps = Readonly<{
  eyebrow: string;
  title: string;
  description: string;
  ctaExplore: string;
  ctaArchitecture: string;
  trustBadges: TrustBadge[];
}>;

export function HeroSection({
  eyebrow,
  title,
  description,
  ctaExplore,
  ctaArchitecture,
  trustBadges,
}: HeroSectionProps) {
  return (
    <section id="hero" aria-labelledby="hero-heading" className="relative overflow-hidden py-20 sm:py-28 lg:py-32">
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(circle_at_top_left,var(--color-primary),transparent_34%),radial-gradient(circle_at_bottom_right,var(--color-accent),transparent_28%)] opacity-15" />
      <div className="mx-auto grid w-full max-w-6xl items-center gap-12 px-6 lg:grid-cols-[1.08fr_0.92fr]">
        <div>
          <Badge variant="outline" className="mb-5 border-primary/30 bg-background/80 text-primary shadow-sm">
            {eyebrow}
          </Badge>
          <h1 id="hero-heading" className="text-4xl font-bold tracking-tight text-foreground sm:text-6xl lg:text-7xl">
            {title}
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-8 text-muted-foreground">{description}</p>
          <div className="mt-10 flex flex-col gap-3 sm:flex-row">
            <Button asChild size="lg">
              <a href="#problem">
                {ctaExplore}
                <ArrowDown aria-hidden="true" />
              </a>
            </Button>
            <Button asChild variant="outline" size="lg">
              <a href="#algorithm-showcase">
                {ctaArchitecture}
                <Boxes aria-hidden="true" />
              </a>
            </Button>
          </div>
        </div>

        <Card className="border-primary/15 bg-card/90 shadow-xl">
          <CardContent className="space-y-5">
            <div className="flex items-center gap-3 rounded-xl border bg-background/70 p-4">
              <span className="flex size-11 items-center justify-center rounded-full bg-primary/10 text-primary">
                <MapPinned aria-hidden="true" className="size-5" />
              </span>
              <div>
                <p className="text-sm font-semibold text-foreground">Ham Ninh AI Guide</p>
                <p className="text-sm text-muted-foreground">RAG · Maps · Ensemble Re-ranking</p>
              </div>
            </div>
            <div className="grid gap-3">
              {trustBadges.map((badge) => (
                <div key={badge.label} className="rounded-xl border bg-background/60 p-4 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
                  <p className="font-semibold text-foreground">{badge.label}</p>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">{badge.description}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
