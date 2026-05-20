import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { AuthCard } from "@/components/auth/auth-card";
import { VerifyEmailForm } from "@/components/auth/verify-email-form";

type Props = Readonly<{
  params: Promise<{ locale: string }>;
  searchParams: Promise<{ email?: string }>;
}>;

export default async function VerifyEmailPage({ params, searchParams }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const { email = "" } = await searchParams;
  const t = await getTranslations("Auth");

  return (
    <AuthCard eyebrow={t("verify.eyebrow")} title={t("verify.title")}>
      <VerifyEmailForm
        locale={locale}
        email={decodeURIComponent(email)}
        translations={{
          instruction: t("verify.instruction"),
          otpLabel: t("verify.otpLabel"),
          otpPlaceholder: t("verify.otpPlaceholder"),
          submitButton: t("verify.submitButton"),
          submitting: t("verify.submitting"),
          resendButton: t("verify.resendButton"),
          resendSuccess: t("verify.resendSuccess"),
          successMessage: t("verify.successMessage"),
          loginLink: t("verify.loginLink"),
        }}
      />
    </AuthCard>
  );
}
