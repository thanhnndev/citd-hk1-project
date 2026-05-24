import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

import { SectionShell } from "./section-shell";

type AlgorithmBar = Readonly<{
  key: string;
  label: string;
  value: number;
  description: string;
}>;

type AlgorithmStep = Readonly<{
  title: string;
  description: string;
}>;

type AlgorithmShowcaseProps = Readonly<{
  eyebrow: string;
  heading: string;
  body: string;
  chart: Readonly<{
    title: string;
    ariaLabel: string;
    description: string;
    bars: AlgorithmBar[];
  }>;
  steps: AlgorithmStep[];
}>;

export function AlgorithmShowcase({ eyebrow, heading, body, chart, steps }: AlgorithmShowcaseProps) {
  return (
    <SectionShell id="algorithm-showcase" eyebrow={eyebrow} heading={heading} body={body} className="bg-muted/35">
      <div className="mt-12 grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
        <Card className="bg-card">
          <CardHeader>
            <CardTitle className="text-xl">{chart.title}</CardTitle>
            <p className="text-sm leading-6 text-muted-foreground">{chart.description}</p>
          </CardHeader>
          <CardContent>
            <div role="img" aria-label={chart.ariaLabel} className="space-y-5">
              {chart.bars.map((bar) => {
                const percentage = Math.round(bar.value * 100);

                return (
                  <div key={bar.key}>
                    <div className="mb-2 flex items-center justify-between gap-3 text-sm">
                      <span className="font-medium text-foreground">{bar.label}</span>
                      <span className="font-semibold tabular-nums text-primary">{percentage}%</span>
                    </div>
                    <div className="h-3 overflow-hidden rounded-full bg-muted">
                      <div className="h-full rounded-full bg-primary transition-all duration-700" style={{ width: `${percentage}%` }} />
                    </div>
                    <p className="mt-2 text-xs leading-5 text-muted-foreground">{bar.description}</p>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4 sm:grid-cols-2">
          {steps.map((step, index) => (
            <Card key={step.title} className="bg-background/70 transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
              <CardContent className="space-y-4">
                <span className="inline-flex size-10 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">
                  {index + 1}
                </span>
                <div>
                  <h3 className="text-lg font-semibold text-foreground">{step.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{step.description}</p>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </SectionShell>
  );
}
