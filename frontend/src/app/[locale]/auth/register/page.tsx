import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { AuthCard } from "@/components/auth/auth-card";
import { RegisterForm } from "@/components/auth/register-form";

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function RegisterPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations("Auth");

  return (
    <AuthCard eyebrow={t("register.eyebrow")} title={t("register.title")}>
      <RegisterForm
        locale={locale}
        translations={{
          usernameLabel: t("register.usernameLabel"),
          usernamePlaceholder: t("register.usernamePlaceholder"),
          emailLabel: t("common.emailLabel"),
          emailPlaceholder: t("register.emailPlaceholder"),
          passwordLabel: t("common.passwordLabel"),
          passwordPlaceholder: t("register.passwordPlaceholder"),
          showPassword: t("common.showPassword"),
          hidePassword: t("common.hidePassword"),
          submitButton: t("register.submitButton"),
          submitting: t("register.submitting"),
          loginPrompt: t("register.loginPrompt"),
          loginLink: t("register.loginLink"),
          successMessage: t("register.successMessage"),
          verifyPrompt: t("register.verifyPrompt"),
        }}
      />
    </AuthCard>
  );
}
