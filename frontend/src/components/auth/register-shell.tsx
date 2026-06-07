import { CircleHelp, Languages, MapPin } from "lucide-react";
import { Link } from "@/i18n/routing";

const HERO_IMAGE = "/images/phu-quoc-login.jpg";

interface RegisterShellProps {
  locale: string;
  title: string;
  description: string;
  heroLineOne: string;
  heroLineTwo: string;
  supportPrompt: string;
  supportLink: string;
  languageLabel: string;
  helpLabel: string;
  copyright: string;
  privacyLabel: string;
  children: React.ReactNode;
}

function RegisterHero({ mobile = false }: { mobile?: boolean }) {
  return (
    <div
      data-testid="register-hero"
      className={
        mobile
          ? "relative h-44 overflow-hidden lg:hidden"
          : "relative hidden min-h-screen overflow-hidden bg-[#001b3c] lg:block"
      }
    >
      <div
        className="absolute inset-0 scale-[1.01] bg-cover bg-center"
        style={{ backgroundImage: `url("${HERO_IMAGE}")` }}
        role="img"
        aria-label="Bờ biển Phú Quốc lúc hoàng hôn"
      />
      <div className="absolute inset-0 bg-[#1d3557]/75" />
      <div className="absolute inset-0 bg-gradient-to-t from-[#001b3c]/80 via-[#001b3c]/20 to-[#001b3c]/30" />
      {mobile && (
        <div className="absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-white to-transparent" />
      )}
    </div>
  );
}

export function RegisterShell({
  locale,
  title,
  description,
  heroLineOne,
  heroLineTwo,
  supportPrompt,
  supportLink,
  languageLabel,
  helpLabel,
  copyright,
  privacyLabel,
  children,
}: RegisterShellProps) {
  const nextLocale = locale === "vi" ? "en" : "vi";

  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto bg-white text-[#001b3c] lg:grid lg:grid-cols-[40%_60%]">
      <RegisterHero mobile />

      <section className="flex min-h-[calc(100dvh-11rem)] flex-col bg-white px-6 py-7 sm:px-10 lg:min-h-screen lg:px-12 lg:py-8 xl:px-16">
        <header className="flex items-center justify-between">
          <Link
            href="/"
            className="flex w-fit items-center gap-2 text-[#0077b6] transition-opacity hover:opacity-75"
            aria-label="Ham Ninh Guide AI"
          >
            <span className="grid h-7 w-7 place-items-center rounded-full border-2 border-[#0077b6]">
              <MapPin className="h-4 w-4" strokeWidth={2.4} />
            </span>
            <span className="text-lg font-extrabold tracking-tight">
              Ham Ninh Guide AI
            </span>
          </Link>

          <div className="flex items-center gap-3">
            <a
              href={`/${nextLocale}/auth/register`}
              className="rounded-sm p-1 text-[#404850] transition-colors hover:text-[#0077b6]"
              aria-label={languageLabel}
              title={languageLabel}
            >
              <Languages className="h-5 w-5" />
            </a>
            <a
              href="mailto:support@phuquoc.vn"
              className="rounded-sm p-1 text-[#404850] transition-colors hover:text-[#0077b6]"
              aria-label={helpLabel}
              title={helpLabel}
            >
              <CircleHelp className="h-5 w-5" />
            </a>
          </div>
        </header>

        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-10 lg:mx-0 lg:py-6">
          <header className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
            <p className="mt-2 max-w-sm text-sm leading-6 text-[#404850]">
              {description}
            </p>
          </header>
          {children}
          <p className="mt-5 text-center text-xs text-[#6b7280]">
            {supportPrompt}{" "}
            <a
              href="mailto:support@phuquoc.vn"
              className="font-semibold text-[#0077b6] hover:underline"
            >
              {supportLink}
            </a>
          </p>
        </div>

        <footer className="flex flex-col gap-3 border-t border-[#e5e7eb] pt-4 text-[11px] leading-4 text-[#6b7280] sm:flex-row sm:items-center sm:justify-between">
          <span>{copyright}</span>
          <div className="flex gap-4">
            <a href="mailto:support@phuquoc.vn" className="hover:text-[#0077b6]">
              IT Support
            </a>
            <span>{privacyLabel}</span>
          </div>
        </footer>
      </section>

      <div className="relative hidden min-h-screen lg:block">
        <RegisterHero />
        <div className="absolute inset-0 z-10 flex items-center justify-center px-12 text-center">
          <div>
            <h2 className="text-4xl font-bold leading-tight tracking-[-0.02em] text-white xl:text-5xl xl:leading-[1.15]">
              {heroLineOne}
              <br />
              {heroLineTwo}
            </h2>
            <div className="mx-auto mt-7 h-1 w-24 rounded-full bg-[#efc13e]/70" />
          </div>
        </div>
      </div>
    </div>
  );
}
