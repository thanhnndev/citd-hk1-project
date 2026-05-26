import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { AuthCard } from "@/components/auth/auth-card";
import { LoginForm } from "@/components/auth/login-form";

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function LoginPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations("Auth");

  return (
    <AuthCard eyebrow={t("login.eyebrow")} title={t("login.title")}>
      <LoginForm
        locale={locale}
        translations={{
          emailLabel: t("common.emailLabel"),
          emailPlaceholder: t("login.emailPlaceholder"),
          passwordLabel: t("common.passwordLabel"),
          passwordPlaceholder: t("login.passwordPlaceholder"),
          showPassword: t("common.showPassword"),
          hidePassword: t("common.hidePassword"),
          submitButton: t("login.submitButton"),
          submitting: t("login.submitting"),
          registerPrompt: t("login.registerPrompt"),
          registerLink: t("login.registerLink"),
          verifyError: t("login.verifyError"),
        }}
      />
    </AuthCard>
  );
}
