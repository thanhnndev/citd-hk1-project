import { Badge } from "@/components/ui/badge";

import { SectionShell } from "./section-shell";

type TechStackItem = Readonly<{
  name: string;
  description: string;
}>;

type TechStackSectionProps = Readonly<{
  eyebrow: string;
  heading: string;
  body: string;
  items: TechStackItem[];
}>;

export function TechStackSection({ eyebrow, heading, body, items }: TechStackSectionProps) {
  return (
    <SectionShell id="tech-stack" eyebrow={eyebrow} heading={heading} body={body}>
      <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <div key={item.name} className="rounded-xl border bg-background/70 p-5 shadow-sm transition-all duration-300 hover:-translate-y-1 hover:shadow-lg">
            <Badge variant="muted" className="mb-4">
              {item.name}
            </Badge>
            <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
          </div>
        ))}
      </div>
    </SectionShell>
  );
}
