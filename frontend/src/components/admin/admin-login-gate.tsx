"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/auth-store";
import { Link } from "@/i18n/routing";
import { LogIn } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

interface AdminLoginGateProps {
  locale: string;
  children: React.ReactNode;
  labels: {
    loginRequired: string;
    loginPrompt: string;
    loginButton: string;
  };
}

export function AdminLoginGate({
  locale: _locale,
  children,
  labels,
}: AdminLoginGateProps) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    setAuthenticated(getToken() !== null);
  }, []);

  // Still checking — render nothing to avoid flash
  if (authenticated === null) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <p className="text-muted-foreground text-sm">{labels.loginRequired}</p>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center px-4">
        <Card className="w-full max-w-md">
          <CardContent className="flex flex-col items-center gap-4 pt-8 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
              <LogIn className="h-6 w-6 text-primary" />
            </div>
            <div>
              <h2 className="text-lg font-semibold">{labels.loginRequired}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {labels.loginPrompt}
              </p>
            </div>
            <Button asChild>
              <Link href="/auth/login">{labels.loginButton}</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <>{children}</>;
}
