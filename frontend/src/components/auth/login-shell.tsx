import {
  CircleHelp,
  Languages,
  MapPin,
} from "lucide-react";
import { Link } from "@/i18n/routing";

const HERO_IMAGE = "/images/phu-quoc-login.jpg";

interface LoginShellProps {
  locale: string;
  title: string;
  description: string;
  heroLineOne: string;
  heroLineTwo: string;
  supportPrompt: string;
  supportLink: string;
  languageLabel: string;
  helpLabel: string;
  children: React.ReactNode;
}

function HeroImage({ mobile = false }: { mobile?: boolean }) {
  return (
    <div
      data-testid="login-hero"
      className={
        mobile
          ? "relative h-48 overflow-hidden lg:hidden"
          : "relative hidden min-h-screen overflow-hidden bg-[#001b3c] lg:block"
      }
    >
      <div
        className="absolute inset-0 scale-[1.01] bg-cover bg-center"
        style={{ backgroundImage: `url("${HERO_IMAGE}")` }}
        role="img"
        aria-label="Bờ biển Phú Quốc lúc hoàng hôn"
      />
      <div className="absolute inset-0 bg-[#1d3557]/20" />
      <div className="absolute inset-0 bg-gradient-to-t from-[#001b3c]/90 via-transparent to-[#001b3c]/10" />
      {mobile && (
        <div className="absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-white to-transparent" />
      )}
    </div>
  );
}

export function LoginShell({
  locale,
  title,
  description,
  heroLineOne,
  heroLineTwo,
  supportPrompt,
  supportLink,
  languageLabel,
  helpLabel,
  children,
}: LoginShellProps) {
  const nextLocale = locale === "vi" ? "en" : "vi";

  return (
    <div className="fixed inset-0 z-[60] overflow-y-auto bg-white text-[#001b3c] lg:grid lg:grid-cols-[40%_60%]">
      <HeroImage mobile />

      <section className="flex min-h-[calc(100dvh-12rem)] flex-col bg-white px-6 py-7 sm:px-10 lg:min-h-screen lg:px-12 lg:py-9 xl:px-16 xl:py-10">
        <Link
          href="/"
          className="flex w-fit items-center gap-2 text-[#0077b6] transition-opacity hover:opacity-75"
          aria-label="Phu Quoc Guide AI"
        >
          <span className="grid h-7 w-7 place-items-center rounded-full border-2 border-[#0077b6]">
            <MapPin className="h-4 w-4" strokeWidth={2.4} />
          </span>
          <span className="text-lg font-extrabold tracking-tight">
            Phu Quoc Guide AI
          </span>
        </Link>

        <div className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-12 lg:mx-0 lg:py-10">
          <header className="mb-8">
            <h1 className="text-2xl font-bold tracking-tight text-[#001b3c]">
              {title}
            </h1>
            <p className="mt-2 max-w-sm text-sm leading-6 text-[#404850]">
              {description}
            </p>
          </header>
          {children}
        </div>

        <footer className="flex flex-col gap-4 border-t border-[#e5e7eb] pt-5 text-xs text-[#6b7280] sm:flex-row sm:items-center sm:justify-between">
          <p>
            {supportPrompt}{" "}
            <a
              href="mailto:support@phuquoc.vn"
              className="font-semibold text-[#0077b6] hover:underline"
            >
              {supportLink}
            </a>
          </p>
          <div className="flex items-center gap-4">
            <a
              href={`/${nextLocale}/auth/login`}
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
        </footer>
      </section>

      <div className="relative hidden min-h-screen lg:block">
        <HeroImage />
        <h2 className="absolute left-12 top-12 z-10 max-w-xl text-4xl font-bold leading-tight tracking-[-0.02em] text-white xl:left-16 xl:top-14 xl:text-5xl xl:leading-[1.15]">
          {heroLineOne}
          <br />
          <span className="text-[#efc13e]">{heroLineTwo}</span>
        </h2>
      </div>
    </div>
  );
}
