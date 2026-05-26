"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { verifyEmail, resendOtp } from "@/lib/auth-api";
import { Link } from "@/i18n/routing";

interface VerifyEmailFormProps {
  locale: string;
  email: string;
  translations: {
    instruction: string;
    otpLabel: string;
    otpPlaceholder: string;
    submitButton: string;
    submitting: string;
    resendButton: string;
    resendSuccess: string;
    successMessage: string;
    loginLink: string;
  };
}

export function VerifyEmailForm({ locale, email, translations }: VerifyEmailFormProps) {
  const router = useRouter();
  const otpInputRef = useRef<HTMLInputElement>(null);
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const [resending, setResending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendMessage, setResendMessage] = useState<string | null>(null);
  const [verified, setVerified] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading || otp.length !== 6) return;

    setError(null);
    setLoading(true);

    try {
      await verifyEmail({ email, otp });
      setVerified(true);
      setTimeout(() => {
        router.push(`/${locale}/auth/login`);
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (resending) return;
    setResendMessage(null);
    setError(null);
    setResending(true);

    try {
      await resendOtp({ email });
      setResendMessage(translations.resendSuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to resend OTP.");
    } finally {
      setResending(false);
    }
  };

  if (verified) {
    return (
      <div className="space-y-3 rounded-xl border border-primary/30 bg-primary/10 px-4 py-6 text-center">
        <p className="font-medium text-foreground">{translations.successMessage}</p>
        <Link
          href="/auth/login"
          className="text-sm font-medium text-primary underline-offset-4 hover:underline"
        >
          {translations.loginLink}
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {/* Instruction */}
      <p className="text-sm text-muted-foreground">
        {translations.instruction}{" "}
        <span className="font-medium text-foreground">{email}</span>
      </p>

      <div className="space-y-1.5">
        <label htmlFor="otp" className="text-sm font-medium text-foreground">
          {translations.otpLabel}
        </label>
        <div
          className="relative grid grid-cols-6 gap-2"
          onClick={() => otpInputRef.current?.focus()}
        >
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              aria-hidden="true"
              className="flex aspect-square items-center justify-center rounded-md border border-input bg-background text-xl font-semibold text-foreground shadow-xs transition-colors"
            >
              {otp[index] ?? ""}
            </div>
          ))}
          <input
            ref={otpInputRef}
            id="otp"
            type="text"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            value={otp}
            onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))}
            disabled={loading}
            className="absolute inset-0 h-full w-full cursor-text opacity-0 disabled:cursor-not-allowed"
            aria-label={translations.otpLabel}
          />
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Resend success */}
      {resendMessage && (
        <div className="rounded-xl border border-primary/20 bg-primary/10 px-3 py-2 text-sm font-medium text-foreground">
          {resendMessage}
        </div>
      )}

      {/* Submit */}
      <Button type="submit" className="w-full" disabled={loading || otp.length !== 6}>
        {loading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            {translations.submitting}
          </>
        ) : (
          translations.submitButton
        )}
      </Button>

      {/* Resend */}
      <Button
        type="button"
        variant="ghost"
        className="w-full text-muted-foreground"
        onClick={handleResend}
        disabled={resending}
      >
        {resending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <RefreshCw className="h-4 w-4" />
        )}
        {translations.resendButton}
      </Button>
    </form>
  );
}
