import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Link } from "@/i18n/routing";

interface AuthCardProps {
  eyebrow: string;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function AuthCard({ eyebrow, title, children, footer }: AuthCardProps) {
  return (
    <div className="flex min-h-[calc(100dvh-8rem)] items-center justify-center px-4 py-12">
      <div className="w-full max-w-md">
        {/* Brand link */}
        <div className="mb-6 text-center">
          <Link
            href="/"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-primary"
          >
            ← Hàm Ninh AI
          </Link>
        </div>

        <Card className="border-border/60 shadow-lg">
          <CardHeader className="pb-2">
            <Badge
              variant="outline"
              className="mb-3 w-fit border-primary/30 bg-background/80 text-primary"
            >
              {eyebrow}
            </Badge>
            <CardTitle className="text-2xl font-bold tracking-tight">
              {title}
            </CardTitle>
          </CardHeader>

          <CardContent className="space-y-4">
            {children}
          </CardContent>

          {footer && (
            <div className="border-t border-border/40 px-6 py-4 text-center text-sm text-muted-foreground">
              {footer}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
