import { BrainCircuit, Map, Scale } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";

import { SectionShell } from "./section-shell";

type SolutionPillar = Readonly<{
  title: string;
  description: string;
}>;

type SolutionSectionProps = Readonly<{
  eyebrow: string;
  heading: string;
  body: string;
  pillars: SolutionPillar[];
}>;

const icons = [BrainCircuit, Map, Scale];

export function SolutionSection({ eyebrow, heading, body, pillars }: SolutionSectionProps) {
  return (
    <SectionShell id="solution" eyebrow={eyebrow} heading={heading} body={body} className="bg-muted/35">
      <div className="mt-12 grid gap-5 lg:grid-cols-3">
        {pillars.map((pillar, index) => {
          const Icon = icons[index % icons.length];

          return (
            <Card key={pillar.title} className="relative overflow-hidden border-primary/10 bg-card">
              <CardContent className="space-y-5">
                <Badge variant="secondary">Agent {index + 1}</Badge>
                <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Icon aria-hidden="true" className="size-5" />
                </div>
                <div>
                  <h3 className="text-xl font-semibold tracking-tight text-foreground">{pillar.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-muted-foreground">{pillar.description}</p>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </SectionShell>
  );
}
