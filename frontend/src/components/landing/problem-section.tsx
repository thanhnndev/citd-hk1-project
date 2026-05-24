import { AlertTriangle, BadgeDollarSign, BookOpenCheck } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { SectionShell } from "./section-shell";

type ProblemCard = Readonly<{
  title: string;
  description: string;
  metric: string;
}>;

type ProblemSectionProps = Readonly<{
  eyebrow: string;
  heading: string;
  body: string;
  cards: ProblemCard[];
}>;

const icons = [AlertTriangle, BadgeDollarSign, BookOpenCheck];

export function ProblemSection({ eyebrow, heading, body, cards }: ProblemSectionProps) {
  return (
    <SectionShell id="problem" eyebrow={eyebrow} heading={heading} body={body}>
      <div className="mt-12 grid gap-5 md:grid-cols-3">
        {cards.map((card, index) => {
          const Icon = icons[index % icons.length];

          return (
            <Card key={card.title} className="h-full bg-background/70 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
              <CardHeader>
                <div className="mb-4 flex size-12 items-center justify-center rounded-xl bg-destructive/10 text-destructive transition-colors duration-300">
                  <Icon aria-hidden="true" className="size-5" />
                </div>
                <CardTitle className="text-xl leading-7">{card.title}</CardTitle>
              </CardHeader>
              <CardContent className="flex grow flex-col gap-5">
                <p className="text-sm leading-6 text-muted-foreground">{card.description}</p>
                <p className="mt-auto rounded-lg border bg-muted/60 px-3 py-2 text-sm font-medium text-foreground">
                  {card.metric}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </SectionShell>
  );
}
