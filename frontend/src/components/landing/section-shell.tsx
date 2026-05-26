import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type SectionShellProps = Readonly<{
  id: string;
  eyebrow: string;
  heading: string;
  body?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
}>;

export function SectionShell({
  id,
  eyebrow,
  heading,
  body,
  children,
  className,
  contentClassName,
}: SectionShellProps) {
  return (
    <section id={id} aria-labelledby={`${id}-heading`} className={cn("scroll-mt-20 py-20 sm:py-28", className)}>
      <div className={cn("mx-auto w-full max-w-6xl px-6", contentClassName)}>
        <div className="mx-auto max-w-3xl text-center">
          <Badge variant="outline" className="mb-4 border-primary/30 bg-primary/5 text-primary transition-colors duration-300">
            {eyebrow}
          </Badge>
          <h2 id={`${id}-heading`} className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
            {heading}
          </h2>
          {body ? <p className="mt-5 text-base leading-8 text-muted-foreground sm:text-lg">{body}</p> : null}
        </div>
        {children}
      </div>
    </section>
  );
}
