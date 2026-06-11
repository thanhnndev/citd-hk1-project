"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Loader2, LockKeyhole, Mail } from "lucide-react";
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
    rememberLogin: string;
    forgotPassword: string;
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
          is_admin: user.is_admin,
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
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      <div>
        <label
          htmlFor="email"
          className="flex items-center gap-2 text-xs font-semibold tracking-[0.04em] text-[#404850]"
        >
          <Mail className="h-4 w-4" aria-hidden="true" />
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
          className="w-full rounded-none border-0 border-b border-[#9aa5b1] bg-transparent px-2 py-3 text-sm text-[#001b3c] outline-none transition-colors placeholder:text-[#6b7280] focus:border-b-2 focus:border-[#0077b6] focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      <div>
        <label
          htmlFor="password"
          className="flex items-center gap-2 text-xs font-semibold tracking-[0.04em] text-[#404850]"
        >
          <LockKeyhole className="h-4 w-4" aria-hidden="true" />
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
            className="w-full rounded-none border-0 border-b border-[#9aa5b1] bg-transparent px-2 py-3 pr-11 text-sm text-[#001b3c] outline-none transition-colors placeholder:text-[#6b7280] focus:border-b-2 focus:border-[#0077b6] focus:ring-0 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute right-1 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center text-[#404850] transition-colors hover:text-[#0077b6]"
            aria-label={showPassword ? translations.hidePassword : translations.showPassword}
          >
            {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between gap-4 pt-1 text-xs">
        <label className="flex cursor-pointer items-center gap-2 font-semibold text-[#404850]">
          <input
            type="checkbox"
            className="h-4 w-4 rounded-sm border-[#9aa5b1] text-[#0077b6] focus:ring-[#0077b6]"
          />
          {translations.rememberLogin}
        </label>
        <button
          type="button"
          className="font-semibold text-[#0077b6] hover:underline"
          title={translations.forgotPassword}
          aria-disabled="true"
        >
          {translations.forgotPassword}
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="border-l-2 border-[#ba1a1a] bg-[#ffdad6]/55 px-3 py-2 text-sm text-[#93000a]"
        >
          {error}
        </div>
      )}

      <button
        type="submit"
        className="flex min-h-12 w-full items-center justify-center gap-2 rounded-sm bg-[#0077b6] px-4 py-3 text-sm font-bold uppercase text-white shadow-[0_5px_12px_rgba(0,93,144,0.18)] transition-[opacity,transform] hover:opacity-90 active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-60"
        disabled={loading}
      >
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            {translations.submitting}
          </>
        ) : (
          translations.submitButton
        )}
      </button>

      <p className="text-center text-xs text-[#6b7280]">
        {translations.registerPrompt}{" "}
        <Link
          href="/auth/register"
          className="font-semibold text-[#0077b6] underline-offset-4 hover:underline"
        >
          {translations.registerLink}
        </Link>
      </p>
    </form>
  );
}
