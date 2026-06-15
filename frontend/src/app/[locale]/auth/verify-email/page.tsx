import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
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
    <div className="flex min-h-screen items-center justify-center bg-[#f9f9ff] p-6">
      <section className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg md:p-12">
        <div className="w-full">
          <div className="mb-8 flex justify-center">
            <span className="rounded-full border border-[#cde5ff] bg-[#005d90]/5 px-3 py-1 text-sm font-semibold tracking-[0.05em] text-[#005d90]">
              {t("verify.eyebrow")}
            </span>
          </div>
          <h1 className="mb-2 text-center text-2xl font-semibold leading-8 tracking-[-0.02em] text-[#001b3c]">
            {t("verify.title")}
          </h1>
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
        </div>
      </section>
    </div>
  );
}
