"use client";

import { Link, usePathname } from "@/i18n/routing";

type HeaderNavigationProps = {
  items: ReadonlyArray<{
    href: "/" | "/chat" | "/map" | "/architecture";
    label: string;
  }>;
};

export function HeaderNavigation({ items }: HeaderNavigationProps) {
  const pathname = usePathname();

  return (
    <ul className="hidden h-16 items-center gap-7 md:flex">
      {items.map(({ href, label }) => {
        const active =
          href === "/" ? pathname === "/" : pathname.startsWith(href);

        return (
          <li key={href} className="h-full">
            <Link
              href={href}
              aria-current={active ? "page" : undefined}
              className={`relative flex h-full items-center px-1 text-sm transition-colors after:absolute after:inset-x-0 after:bottom-0 after:h-[2px] after:origin-center after:bg-[#005d90] after:transition-transform ${
                active
                  ? "font-bold text-[#005d90] after:scale-x-100"
                  : "font-medium text-[#404850] hover:text-[#005d90] after:scale-x-0 hover:after:scale-x-100"
              }`}
            >
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
