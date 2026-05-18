import { CheckCircle2 } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

import { SectionShell } from "./section-shell";

type ResponsibleAxis = Readonly<{
  id: string;
  title: string;
  description: string;
  metric: string;
}>;

type ResponsibleAiSectionProps = Readonly<{
  eyebrow: string;
  heading: string;
  body: string;
  axes: ResponsibleAxis[];
}>;

export function ResponsibleAiSection({ eyebrow, heading, body, axes }: ResponsibleAiSectionProps) {
  return (
    <SectionShell id="responsible-ai" eyebrow={eyebrow} heading={heading} body={body}>
      <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-5">
        {axes.map((axis, index) => (
          <Card key={axis.id} className="bg-background/70">
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-primary">0{index + 1}</span>
                <CheckCircle2 aria-hidden="true" className="size-5 text-primary" />
              </div>
              <div>
                <h3 className="text-lg font-semibold tracking-tight text-foreground">{axis.title}</h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{axis.description}</p>
              </div>
              <p className="rounded-lg border bg-muted/60 px-3 py-2 text-xs font-medium leading-5 text-foreground">
                <span className="sr-only">Metric: </span>
                {axis.metric}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>
    </SectionShell>
  );
}
