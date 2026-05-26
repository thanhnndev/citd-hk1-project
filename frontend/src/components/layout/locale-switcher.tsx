"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter, usePathname } from "@/i18n/routing";
import { useState } from "react";

const locales = [
  { value: "vi", label: "Tiếng Việt", flag: "🇻🇳" },
  { value: "en", label: "English", flag: "🇬🇧" },
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
        className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-600 rounded-lg border border-transparent transition-all duration-200 hover:border-gray-200 hover:shadow-md hover:-translate-y-0.5 dark:text-gray-300 dark:hover:border-gray-600"
      >
        <span>{current.flag}</span>
        <span>{current.label}</span>
        <svg
          className={`w-3 h-3 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <>
          {/* backdrop */}
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          {/* dropdown */}
          <div className="absolute right-0 z-20 mt-1 w-36 rounded-lg border border-gray-200 bg-white shadow-lg dark:border-gray-700 dark:bg-gray-900">
            {locales.map(({ value, label, flag }) => (
              <button
                key={value}
                onClick={() => handleSelect(value)}
                className={`flex w-full items-center gap-2 px-3 py-2 text-sm transition-colors first:rounded-t-lg last:rounded-b-lg
                  ${value === locale
                    ? "bg-gray-100 font-medium text-gray-900 dark:bg-gray-800 dark:text-white"
                    : "text-gray-600 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-gray-800"
                  }`}
              >
                <span>{flag}</span>
                <span>{label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}