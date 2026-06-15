import {
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  MapPinned,
  MessageCircle,
  ShieldCheck,
  Sparkles,
  UtensilsCrossed,
  Zap,
} from "lucide-react";
import Image from "next/image";
import { Link } from "@/i18n/routing";

type Stat = Readonly<{ label: string; value: string }>;
type Benefit = Readonly<{ title: string; description: string }>;
type Step = Readonly<{ title: string; description: string }>;

export type TourismHomepageContent = Readonly<{
  hero: {
    eyebrow: string;
    titleStart: string;
    titleHighlight: string;
    titleEnd: string;
    description: string;
    exampleLabel: string;
    exampleQuestion: string;
    suggestions: string[];
    primaryCta: string;
    secondaryCta: string;
    freeNote: string;
    realtimeLabel: string;
    realtimeValue: string;
    placesValue: string;
    placesLabel: string;
    trustLabel: string;
  };
  stats: Stat[];
  benefits: {
    heading: string;
    items: Benefit[];
  };
  steps: {
    heading: string;
    items: Step[];
  };
  cta: {
    heading: string;
    description: string;
    button: string;
  };
  footer: {
    brand: string;
    description: string;
    quickLinks: string;
    support: string;
    privacy: string;
    terms: string;
    contact: string;
    copyright: string;
    disclaimer: string;
  };
}>;

const benefitIcons = [Bot, UtensilsCrossed, Zap];

export function TourismHomepage({
  content,
}: {
  content: TourismHomepageContent;
}) {
  return (
    <div className="bg-white text-[#001b3c]">
      <section
        id="homepage-hero"
        className="relative overflow-hidden bg-gradient-to-br from-white via-[#f9f9ff] to-[#e7eeff] px-6 py-16 sm:py-20 lg:px-8 lg:py-24"
      >
        <div className="mx-auto grid max-w-7xl items-center gap-14 lg:grid-cols-[1fr_0.92fr]">
          <div className="relative z-10">
            <div className="mb-5 inline-flex items-center gap-2 rounded-full bg-[#0077b6]/10 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.14em] text-[#005d90]">
              <Sparkles className="h-4 w-4" />
              {content.hero.eyebrow}
            </div>

            <h1 className="max-w-3xl text-4xl font-bold leading-[1.1] tracking-[-0.035em] sm:text-5xl lg:text-6xl">
              {content.hero.titleStart}{" "}
              <span className="text-[#005d90]">
                {content.hero.titleHighlight}
              </span>{" "}
              {content.hero.titleEnd}
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-7 text-[#404850] sm:text-lg">
              {content.hero.description}
            </p>

            <div className="mt-8 max-w-xl rounded-xl border border-[#bfc7d1] bg-white p-4 shadow-sm">
              <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-[#6b7280]">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                {content.hero.exampleLabel}
              </div>
              <div className="flex items-start justify-between gap-3 rounded-lg border-b border-[#bfc7d1] bg-[#f0f3ff] px-4 py-3 text-sm text-[#404850]">
                <span>
                  {content.hero.exampleQuestion}
                </span>
                <MessageCircle className="h-5 w-5 shrink-0 text-[#0077b6]/45" />
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {content.hero.suggestions.map((suggestion) => (
                  <span
                    key={suggestion}
                    className="rounded-full border border-[#0077b6]/20 bg-[#0077b6]/10 px-3 py-1 text-xs font-semibold text-[#005d90]"
                  >
                    {suggestion}
                  </span>
                ))}
              </div>
            </div>

            <div className="mt-8 flex flex-col gap-4 sm:flex-row sm:items-center">
              <Link
                href="/chat"
                className="inline-flex min-h-12 items-center justify-center gap-2 rounded-sm bg-[#005d90] px-7 py-3 text-sm font-bold text-white transition hover:bg-[#0077b6]"
              >
                {content.hero.primaryCta}
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/architecture"
                className="inline-flex min-h-12 items-center justify-center rounded-sm border border-[#bfc7d1] bg-white px-7 py-3 text-sm font-bold text-[#005d90] transition hover:border-[#0077b6]"
              >
                {content.hero.secondaryCta}
              </Link>
            </div>
            <p className="mt-4 flex items-center gap-2 text-xs text-[#6b7280]">
              <ShieldCheck className="h-4 w-4" />
              {content.hero.freeNote}
            </p>
          </div>

          <div className="relative mx-auto w-full max-w-2xl">
            <div className="absolute -right-12 -top-12 h-56 w-56 rounded-full bg-[#0077b6]/10 blur-3xl" />
            <div className="relative overflow-hidden rounded-[24px] border-[7px] border-[#001b3c] bg-[#001b3c] shadow-2xl">
              <Image
                src="/images/ham-ninh-homepage.jpg"
                alt="Làng chài Hàm Ninh nhìn từ trên cao"
                width={1024}
                height={768}
                priority
                className="aspect-[4/3] w-full object-cover"
              />
              <div className="absolute right-4 top-4 rounded-xl border border-white/70 bg-white/90 p-3 shadow-lg backdrop-blur">
                <div className="flex items-center gap-3">
                  <span className="rounded-lg bg-[#fece4b] p-2 text-[#725800]">
                    <Clock3 className="h-5 w-5" />
                  </span>
                  <div>
                    <p className="text-[10px] text-[#6b7280]">
                      {content.hero.realtimeLabel}
                    </p>
                    <p className="text-sm font-bold">
                      {content.hero.realtimeValue}
                    </p>
                  </div>
                </div>
              </div>
              <div className="absolute bottom-4 left-4 rounded-xl border border-white/70 bg-white/90 p-4 shadow-lg backdrop-blur">
                <div className="flex items-center gap-4">
                  <div>
                    <p className="text-2xl font-bold text-[#005d90]">
                      {content.hero.placesValue}
                    </p>
                    <p className="text-xs text-[#6b7280]">
                      {content.hero.placesLabel}
                    </p>
                  </div>
                  <div className="h-10 w-px bg-[#bfc7d1]" />
                  <div className="flex items-center gap-2 text-xs font-bold">
                    <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                    {content.hero.trustLabel}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="homepage-stats" className="bg-[#005d90] px-6 py-7 text-white">
        <div className="mx-auto grid max-w-7xl grid-cols-2 gap-6 md:grid-cols-4">
          {content.stats.map((stat, index) => (
            <div
              key={stat.label}
              className={`text-center md:text-left ${
                index < content.stats.length - 1
                  ? "md:border-r md:border-white/20"
                  : ""
              }`}
            >
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-white/65">
                {stat.label}
              </p>
              <p className="mt-1 text-lg font-bold">{stat.value}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="homepage-benefits" className="px-6 py-16 sm:py-20">
        <div className="mx-auto max-w-7xl">
          <header className="mb-12 text-center">
            <h2 className="text-3xl font-bold tracking-tight">
              {content.benefits.heading}
            </h2>
            <div className="mx-auto mt-4 h-1 w-20 rounded-full bg-[#0077b6]" />
          </header>
          <div className="grid gap-6 md:grid-cols-3">
            {content.benefits.items.map((item, index) => {
              const Icon = benefitIcons[index % benefitIcons.length];
              return (
                <article
                  key={item.title}
                  className="border border-[#bfc7d1] bg-[#f9f9ff] p-7 transition hover:-translate-y-1 hover:border-[#0077b6]/50 hover:shadow-lg"
                >
                  <span className="mb-5 flex h-12 w-12 items-center justify-center rounded-lg bg-[#0077b6]/10 text-[#005d90]">
                    <Icon className="h-6 w-6" />
                  </span>
                  <h3 className="text-xl font-bold">{item.title}</h3>
                  <p className="mt-3 text-sm leading-6 text-[#404850]">
                    {item.description}
                  </p>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section id="homepage-steps" className="bg-[#f0f3ff] px-6 py-16 sm:py-20">
        <div className="mx-auto max-w-7xl">
          <h2 className="text-center text-3xl font-bold tracking-tight">
            {content.steps.heading}
          </h2>
          <div className="relative mt-12 grid gap-8 md:grid-cols-3">
            <div className="absolute left-[16%] right-[16%] top-7 hidden h-px bg-[#bfc7d1] md:block" />
            {content.steps.items.map((item, index) => (
              <article
                key={item.title}
                className="relative flex flex-col items-center text-center"
              >
                <span className="relative z-10 flex h-14 w-14 items-center justify-center rounded-full bg-[#005d90] text-lg font-bold text-white ring-8 ring-[#f0f3ff]">
                  {index + 1}
                </span>
                <h3 className="mt-6 text-lg font-bold">{item.title}</h3>
                <p className="mt-2 max-w-sm text-sm leading-6 text-[#404850]">
                  {item.description}
                </p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section
        id="homepage-cta"
        className="relative overflow-hidden bg-gradient-to-r from-[#005d90] to-[#0077b6] px-6 py-20 text-center text-white"
      >
        <div className="absolute -bottom-32 -right-24 h-80 w-80 rounded-full bg-white/10" />
        <div className="relative mx-auto max-w-3xl">
          <h2 className="text-3xl font-bold tracking-tight sm:text-4xl">
            {content.cta.heading}
          </h2>
          <p className="mx-auto mt-5 max-w-2xl text-sm leading-7 text-white/80 sm:text-base">
            {content.cta.description}
          </p>
          <Link
            href="/chat"
            className="mt-8 inline-flex min-h-12 items-center justify-center gap-2 rounded-sm border-2 border-white bg-white px-8 py-3 text-sm font-bold text-[#005d90] transition hover:bg-transparent hover:text-white"
          >
            {content.cta.button}
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </section>

      <footer className="border-t border-[#bfc7d1] bg-[#f0f3ff] px-6 py-10">
        <div className="mx-auto max-w-7xl">
          <div className="flex flex-col justify-between gap-8 md:flex-row">
            <div className="max-w-sm">
              <p className="text-lg font-bold">{content.footer.brand}</p>
              <p className="mt-2 text-xs leading-5 text-[#6b7280]">
                {content.footer.description}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-10 text-xs">
              <div className="flex flex-col gap-2">
                <span className="font-bold uppercase tracking-wide">
                  {content.footer.quickLinks}
                </span>
                <span className="text-[#6b7280]">{content.footer.privacy}</span>
                <span className="text-[#6b7280]">{content.footer.terms}</span>
              </div>
              <div className="flex flex-col gap-2">
                <span className="font-bold uppercase tracking-wide">
                  {content.footer.support}
                </span>
                <a
                  href="mailto:support@phuquoc.vn"
                  className="text-[#6b7280] hover:text-[#005d90]"
                >
                  {content.footer.contact}
                </a>
                <Link href="/map" className="text-[#6b7280] hover:text-[#005d90]">
                  <span className="inline-flex items-center gap-1">
                    <MapPinned className="h-3.5 w-3.5" />
                    Map
                  </span>
                </Link>
              </div>
            </div>
          </div>
          <div className="mt-8 flex flex-col gap-3 border-t border-[#bfc7d1] pt-6 text-[10px] text-[#6b7280] md:flex-row md:items-center md:justify-between">
            <span>{content.footer.copyright}</span>
            <span>{content.footer.disclaimer}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
