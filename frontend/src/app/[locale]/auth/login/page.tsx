import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { LoginForm } from "@/components/auth/login-form";
import { LoginShell } from "@/components/auth/login-shell";

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function LoginPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations("Auth");

  return (
    <LoginShell
      locale={locale}
      title={t("login.title")}
      description={t("login.description")}
      heroLineOne={t("login.heroLineOne")}
      heroLineTwo={t("login.heroLineTwo")}
      supportPrompt={t("login.supportPrompt")}
      supportLink={t("login.supportLink")}
      languageLabel={t("login.languageLabel")}
      helpLabel={t("login.helpLabel")}
    >
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
          rememberLogin: t("login.rememberLogin"),
          forgotPassword: t("login.forgotPassword"),
        }}
      />
    </LoginShell>
  );
}
