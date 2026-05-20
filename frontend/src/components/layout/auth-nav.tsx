"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { LogIn, LogOut, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Link } from "@/i18n/routing";
import {
  AUTH_CHANGED_EVENT,
  getUser,
  logout,
  isLoggedIn,
} from "@/lib/auth-store";

interface AuthNavProps {
  locale: string;
  translations: {
    login: string;
    register: string;
    logout: string;
  };
}

export function AuthNav({ locale, translations }: AuthNavProps) {
  const router = useRouter();
  const [loggedIn, setLoggedIn] = useState(false);
  const [username, setUsername] = useState<string | null>(null);

  const syncAuthState = () => {
    setLoggedIn(isLoggedIn());
    setUsername(getUser()?.username ?? null);
  };

  useEffect(() => {
    syncAuthState();

    window.addEventListener(AUTH_CHANGED_EVENT, syncAuthState);
    window.addEventListener("storage", syncAuthState);
    window.addEventListener("focus", syncAuthState);

    return () => {
      window.removeEventListener(AUTH_CHANGED_EVENT, syncAuthState);
      window.removeEventListener("storage", syncAuthState);
      window.removeEventListener("focus", syncAuthState);
    };
  }, []);

  const handleLogout = () => {
    logout();
    setLoggedIn(false);
    setUsername(null);
    router.push(`/${locale}`);
    router.refresh();
  };

  if (loggedIn) {
    return (
      <div className="flex items-center gap-2">
        {username && (
          <span className="hidden text-sm font-medium text-foreground sm:block">
            {username}
          </span>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={handleLogout}
          className="gap-1.5 text-muted-foreground hover:text-foreground"
          aria-label={translations.logout}
          title={translations.logout}
        >
          <LogOut className="h-4 w-4" />
          <span className="hidden sm:inline">{translations.logout}</span>
        </Button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Button variant="ghost" size="sm" asChild className="gap-1.5">
        <Link href="/auth/login" aria-label={translations.login} title={translations.login}>
          <LogIn className="h-4 w-4" />
          <span className="hidden sm:inline">{translations.login}</span>
        </Link>
      </Button>
      <Button size="sm" asChild className="gap-1.5">
        <Link href="/auth/register" aria-label={translations.register} title={translations.register}>
          <UserPlus className="h-4 w-4" />
          <span className="hidden sm:inline">{translations.register}</span>
        </Link>
      </Button>
    </div>
  );
}
