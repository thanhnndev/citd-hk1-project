import { getTranslations, setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { AdminLoginGate } from "@/components/admin/admin-login-gate";
import { AdminDashboard } from "@/components/admin/admin-dashboard";

type Props = Readonly<{ params: Promise<{ locale: string }> }>;

export default async function AdminPage({ params }: Props) {
  const { locale } = await params;
  if (!routing.locales.includes(locale as (typeof routing.locales)[number]))
    notFound();
  setRequestLocale(locale);

  const t = await getTranslations("Admin");

  return (
    <div className="container mx-auto px-4 py-8">
      <AdminLoginGate
        locale={locale}
        labels={{
          loginRequired: t("gate.loginRequired"),
          loginPrompt: t("gate.loginPrompt"),
          loginButton: t("gate.loginButton"),
        }}
      >
        <AdminDashboard
          labels={{
            title: t("dashboard.title"),
            corpus: {
              title: t("dashboard.corpus.title"),
              noData: t("dashboard.corpus.noData"),
            },
            evaluation: {
              title: t("dashboard.evaluation.title"),
              triggerButton: t("dashboard.evaluation.triggerButton"),
              triggering: t("dashboard.evaluation.triggering"),
              lastVerdict: t("dashboard.evaluation.lastVerdict"),
              noResults: t("dashboard.evaluation.noResults"),
              error: t("dashboard.evaluation.error"),
            },
            traces: {
              title: t("dashboard.traces.title"),
              enabled: t("dashboard.traces.enabled"),
              disabled: t("dashboard.traces.disabled"),
              noData: t("dashboard.traces.noData"),
              error: t("dashboard.traces.error"),
            },
            fairness: {
              title: t("dashboard.fairness.title"),
              totalAudits: t("dashboard.fairness.totalAudits"),
              meanLocalFactor: t("dashboard.fairness.meanLocalFactor"),
              noData: t("dashboard.fairness.noData"),
              error: t("dashboard.fairness.error"),
            },
            fetchError: t("dashboard.fetchError"),
          }}
        />
      </AdminLoginGate>
    </div>
  );
}
