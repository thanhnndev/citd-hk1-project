"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter, usePathname } from "@/i18n/routing";
import { useState } from "react";
import { ChevronDown, Globe2 } from "lucide-react";

const locales = [
  { value: "vi", label: "Tiếng Việt" },
  { value: "en", label: "English" },
];

export function LocaleSwitcher() {
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const t = useTranslations("Navigation");
  const [open, setOpen] = useState(false);

  const current = locales.find((l) => l.value === locale) ?? locales[0];

  function handleSelect(nextLocale: string) {
    setOpen(false);
    router.push(pathname, { locale: nextLocale });
  }

  return (
    <div className="relative" aria-label={t.raw("localeSwitcherLabel")}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex h-10 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-[#404850] transition-colors hover:bg-[#f0f3ff] sm:px-3 sm:text-sm"
        aria-expanded={open}
      >
        <Globe2 className="h-4 w-4" />
        <span className="hidden sm:inline">{current.label}</span>
        <ChevronDown className={`h-3.5 w-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>

      {open && (
        <>
          {/* backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          {/* dropdown */}
          <div className="absolute right-0 z-20 mt-1 w-36 rounded-lg border border-[#e5e7eb] bg-white py-1 shadow-lg">
            {locales.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => handleSelect(value)}
                className={`flex w-full items-center px-3 py-2 text-sm transition-colors
                  ${value === locale
                    ? "bg-[#f0f3ff] font-semibold text-[#005d90]"
                    : "text-[#404850] hover:bg-[#f9f9ff]"
                  }`}
              >
                <span>{label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
