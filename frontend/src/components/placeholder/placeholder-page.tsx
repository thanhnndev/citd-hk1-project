import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { cn } from "@/lib/utils";

interface PlaceholderPageProps {
  title: string;
  description: string;
  comingSoonLabel: string;
  statusUnderConstruction: string;
  backToLandingLabel: string;
}

export default function PlaceholderPage({
  title,
  description,
  comingSoonLabel,
  statusUnderConstruction,
  backToLandingLabel,
}: PlaceholderPageProps) {
  return (
    <div className={cn("flex min-h-screen items-center justify-center p-6")}>
      <Card className="w-full max-w-lg">
        <CardHeader className="space-y-4">
          <div className="flex items-center justify-between">
            <Badge variant="secondary">{comingSoonLabel}</Badge>
          </div>
          <CardTitle className="text-2xl">{title}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">{statusUnderConstruction}</p>
          <p className="text-muted-foreground">{description}</p>
          <Link
            href="/"
            className="text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {backToLandingLabel}
          </Link>
        </CardContent>
      </Card>
    </div>
  );
}
