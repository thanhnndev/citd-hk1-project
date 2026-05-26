"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { login } from "@/lib/auth-api";
import { saveToken, saveUser } from "@/lib/auth-store";
import { Link } from "@/i18n/routing";

interface LoginFormProps {
  locale: string;
  translations: {
    emailLabel: string;
    emailPlaceholder: string;
    passwordLabel: string;
    passwordPlaceholder: string;
    showPassword: string;
    hidePassword: string;
    submitButton: string;
    submitting: string;
    registerPrompt: string;
    registerLink: string;
    verifyError: string;
  };
}

export function LoginForm({ locale, translations }: LoginFormProps) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;

    setError(null);
    setLoading(true);

    try {
      const tokenRes = await login({ email, password });
      saveToken(tokenRes.access_token);

      // Fetch user profile and cache it
      const meRes = await fetch("/api/auth/me", {
        headers: { Authorization: `Bearer ${tokenRes.access_token}` },
      });
      if (meRes.ok) {
        const user = await meRes.json();
        saveUser({
          id: user.id,
          username: user.username,
          email: user.email,
          is_verified: user.is_verified,
        });
      }

      router.push(`/${locale}/chat`);
      router.refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Login failed.";
      // Surface the email-not-verified message clearly
      if (msg.toLowerCase().includes("not verified")) {
        setError(translations.verifyError);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <div className="space-y-1.5">
        <label htmlFor="email" className="text-sm font-medium text-foreground">
          {translations.emailLabel}
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={translations.emailPlaceholder}
          disabled={loading}
          className="w-full rounded-xl border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium text-foreground">
          {translations.passwordLabel}
        </label>
        <div className="relative">
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={translations.passwordPlaceholder}
            disabled={loading}
            className="w-full rounded-xl border border-input bg-background px-3 py-2 pr-10 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            aria-label={showPassword ? translations.hidePassword : translations.showPassword}
          >
            {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Submit */}
      <Button type="submit" className="w-full" disabled={loading}>
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            {translations.submitting}
          </>
        ) : (
          translations.submitButton
        )}
      </Button>

      {/* Register link */}
      <p className="text-center text-sm text-muted-foreground">
        {translations.registerPrompt}{" "}
        <Link
          href="/auth/register"
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          {translations.registerLink}
        </Link>
      </p>
    </form>
  );
}
