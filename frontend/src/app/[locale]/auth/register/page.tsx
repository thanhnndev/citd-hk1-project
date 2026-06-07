import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { RegisterForm } from "@/components/auth/register-form";
import { RegisterShell } from "@/components/auth/register-shell";

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function RegisterPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number])) notFound();
  setRequestLocale(locale);

  const t = await getTranslations("Auth");

  return (
    <RegisterShell
      locale={locale}
      title={t("register.title")}
      description={t("register.description")}
      heroLineOne={t("register.heroLineOne")}
      heroLineTwo={t("register.heroLineTwo")}
      supportPrompt={t("register.supportPrompt")}
      supportLink={t("register.supportLink")}
      languageLabel={t("register.languageLabel")}
      helpLabel={t("register.helpLabel")}
      copyright={t("register.copyright")}
      privacyLabel={t("register.privacyLabel")}
    >
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
          confirmPasswordLabel: t("register.confirmPasswordLabel"),
          confirmPasswordPlaceholder: t("register.confirmPasswordPlaceholder"),
          passwordMismatch: t("register.passwordMismatch"),
        }}
      />
    </RegisterShell>
  );
}
