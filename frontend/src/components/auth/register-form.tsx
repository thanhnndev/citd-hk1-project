"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Eye, EyeOff } from "lucide-react";
import { register } from "@/lib/auth-api";
import { Link } from "@/i18n/routing";

interface RegisterFormProps {
  locale: string;
  translations: {
    usernameLabel: string;
    usernamePlaceholder: string;
    emailLabel: string;
    emailPlaceholder: string;
    passwordLabel: string;
    passwordPlaceholder: string;
    showPassword: string;
    hidePassword: string;
    submitButton: string;
    submitting: string;
    loginPrompt: string;
    loginLink: string;
    successMessage: string;
    verifyPrompt: string;
    confirmPasswordLabel: string;
    confirmPasswordPlaceholder: string;
    passwordMismatch: string;
  };
}

export function RegisterForm({ locale, translations }: RegisterFormProps) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;

    setError(null);
    if (password !== confirmPassword) {
      setError(translations.passwordMismatch);
      return;
    }
    setLoading(true);

    try {
      await register({ username, email, password });
      setSuccess(true);

      setTimeout(() => {
        router.push(`/${locale}/auth/verify-email?email=${encodeURIComponent(email)}`);
      }, 1500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div className="border-l-2 border-[#0077b6] bg-[#cde5ff]/45 px-4 py-6 text-center">
        <p className="font-medium text-[#001b3c]">
          {translations.verifyPrompt}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      <div>
        <label htmlFor="username" className="text-xs font-semibold uppercase tracking-[0.06em] text-[#404850]">
          {translations.usernameLabel}
        </label>
        <input
          id="username"
          type="text"
          autoComplete="username"
          required
          minLength={3}
          maxLength={50}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder={translations.usernamePlaceholder}
          disabled={loading}
          className="w-full rounded-none border-0 border-b border-[#bfc7d1] bg-transparent px-2 py-2.5 text-sm text-[#001b3c] outline-none placeholder:text-[#6b7280] focus:border-b-2 focus:border-[#0077b6] focus:ring-0 disabled:opacity-50"
        />
      </div>

      <div>
        <label htmlFor="email" className="text-xs font-semibold uppercase tracking-[0.06em] text-[#404850]">
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
          className="w-full rounded-none border-0 border-b border-[#bfc7d1] bg-transparent px-2 py-2.5 text-sm text-[#001b3c] outline-none placeholder:text-[#6b7280] focus:border-b-2 focus:border-[#0077b6] focus:ring-0 disabled:opacity-50"
        />
      </div>

      <div>
        <label htmlFor="password" className="text-xs font-semibold uppercase tracking-[0.06em] text-[#404850]">
          {translations.passwordLabel}
        </label>
        <div className="relative">
          <input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            required
            minLength={6}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={translations.passwordPlaceholder}
            disabled={loading}
            className="w-full rounded-none border-0 border-b border-[#bfc7d1] bg-transparent px-2 py-2.5 pr-11 text-sm text-[#001b3c] outline-none placeholder:text-[#6b7280] focus:border-b-2 focus:border-[#0077b6] focus:ring-0 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute right-0 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center text-[#404850] hover:text-[#0077b6]"
            aria-label={showPassword ? translations.hidePassword : translations.showPassword}
          >
            {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
          </button>
        </div>
      </div>

      <div>
        <label htmlFor="confirm_password" className="text-xs font-semibold uppercase tracking-[0.06em] text-[#404850]">
          {translations.confirmPasswordLabel}
        </label>
        <div className="relative">
          <input
            id="confirm_password"
            type={showConfirmPassword ? "text" : "password"}
            autoComplete="new-password"
            required
            minLength={6}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder={translations.confirmPasswordPlaceholder}
            disabled={loading}
            className="w-full rounded-none border-0 border-b border-[#bfc7d1] bg-transparent px-2 py-2.5 pr-11 text-sm text-[#001b3c] outline-none placeholder:text-[#6b7280] focus:border-b-2 focus:border-[#0077b6] focus:ring-0 disabled:opacity-50"
          />
          <button
            type="button"
            onClick={() => setShowConfirmPassword((value) => !value)}
            className="absolute right-0 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center text-[#404850] hover:text-[#0077b6]"
            aria-label={
              showConfirmPassword
                ? translations.hidePassword
                : translations.showPassword
            }
          >
            {showConfirmPassword ? (
              <EyeOff className="h-5 w-5" />
            ) : (
              <Eye className="h-5 w-5" />
            )}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="border-l-2 border-[#ba1a1a] bg-[#ffdad6]/55 px-3 py-2 text-sm text-[#93000a]">
          {error}
        </div>
      )}

      <button
        type="submit"
        className="flex min-h-12 w-full items-center justify-center gap-2 rounded-sm bg-[#0077b6] px-4 py-3 text-sm font-bold uppercase text-white shadow-[0_5px_12px_rgba(0,93,144,0.18)] transition-[opacity,transform] hover:opacity-90 active:scale-[0.99] disabled:opacity-60"
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
        {translations.loginPrompt}{" "}
        <Link
          href="/auth/login"
          className="font-semibold text-[#0077b6] underline-offset-4 hover:underline"
        >
          {translations.loginLink}
        </Link>
      </p>
    </form>
  );
}
