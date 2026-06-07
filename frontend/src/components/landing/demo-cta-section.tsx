"use client";

import { ArrowRight, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { SectionShell } from "./section-shell";

type DemoItem = Readonly<{
  title: string;
  description: string;
}>;

type DemoCtaSectionProps = Readonly<{
  locale: string;
  eyebrow: string;
  heading: string;
  body: string;
  primaryCta: string;
  secondaryCta: string;
  note: string;
  items: DemoItem[];
}>;

export function DemoCtaSection({
  locale,
  eyebrow,
  heading,
  body,
  primaryCta,
  secondaryCta,
  note,
  items,
}: DemoCtaSectionProps) {
  return (
    <SectionShell id="demo" eyebrow={eyebrow} heading={heading} body={body} className="bg-primary/5">
      <div className="mt-12 grid gap-6 lg:grid-cols-[1fr_0.85fr]">
        <Card className="border-primary/20 bg-card">
          <CardContent className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              {items.map((item) => (
                <div key={item.title} className="rounded-xl border bg-background/70 p-4 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
                  <h3 className="font-semibold text-foreground">{item.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.description}</p>
                </div>
              ))}
            </div>
            <p className="rounded-xl border border-primary/20 bg-primary/5 p-4 text-sm leading-6 text-muted-foreground">
              {note}
            </p>
          </CardContent>
        </Card>

        <Card className="justify-center bg-background/80">
          <CardContent className="space-y-5 text-center lg:text-left">
            <h3 className="text-2xl font-semibold tracking-tight text-foreground">Ham Ninh AI Guide</h3>
            <p className="text-sm leading-6 text-muted-foreground">{note}</p>
            <div className="flex flex-col gap-3 sm:flex-row lg:flex-col xl:flex-row">
              <Button asChild size="lg" className="transition-transform hover:scale-[1.02]">
                <a href={`/${locale}/chat`} aria-label={`${primaryCta} (preview route)`}>
                  {primaryCta}
                  <ArrowRight aria-hidden="true" />
                </a>
              </Button>
              <Button asChild variant="outline" size="lg" className="transition-transform hover:scale-[1.02]">
                <a href={`/${locale}/architecture`} aria-label={`${secondaryCta} (coming soon route)`}>
                  {secondaryCta}
                  <ExternalLink aria-hidden="true" />
                </a>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </SectionShell>
  );
}
