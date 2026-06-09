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
      <div className="mt-8 space-y-3 rounded-xl border border-[#cde5ff] bg-[#005d90]/10 px-4 py-6 text-center">
        <p className="font-semibold text-[#001b3c]">{translations.successMessage}</p>
        <Link
          href="/auth/login"
          className="text-sm font-bold text-[#005d90] underline-offset-4 hover:underline"
        >
          {translations.loginLink}
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-8" noValidate>
      <p className="mb-8 text-center text-base leading-6 text-[#404850]">
        {translations.instruction}{" "}
        <span className="block font-bold text-[#001b3c]">{email}</span>
      </p>

      <div className="flex flex-col gap-2">
        <label htmlFor="otp" className="text-sm font-semibold uppercase tracking-wider text-[#707881]">
          {translations.otpLabel}
        </label>
        <div
          className="relative mb-8 flex justify-center gap-2"
          onClick={() => otpInputRef.current?.focus()}
        >
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={index}
              aria-hidden="true"
              style={{ height: 44, minWidth: 44, width: 44 }}
              className={[
                "flex items-center justify-center border bg-transparent text-2xl font-bold text-[#001b3c] transition-colors",
                index === otp.length ? "border-2 border-[#005d90]" : "border-[#707881]",
              ].join(" ")}
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
        <div className="rounded-xl border border-[#cde5ff] bg-[#005d90]/10 px-3 py-2 text-sm font-semibold text-[#001b3c]">
          {resendMessage}
        </div>
      )}

      {/* Submit */}
      <Button
        type="submit"
        className="h-auto w-full rounded-lg bg-[#0077b6] py-4 text-base font-semibold text-white shadow-lg shadow-[#0077b6]/20 transition hover:bg-[#005d90] active:scale-[0.98]"
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
      </Button>

      {/* Resend */}
      <Button
        type="button"
        variant="ghost"
        className="mx-auto flex w-fit gap-2 text-base font-semibold text-[#005d90] hover:bg-transparent hover:text-[#004b74] hover:underline"
        onClick={handleResend}
        disabled={resending}
      >
        {resending ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : (
          <RefreshCw className="h-5 w-5" />
        )}
        {translations.resendButton}
      </Button>
    </form>
  );
}
