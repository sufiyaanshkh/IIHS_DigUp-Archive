import Link from "next/link";
import { Archive, Search } from "lucide-react";

export function ArchiveSectionNav({ active }: { active: "search" | "all-archive" }) {
  const links = [
    { href: "/archive", label: "Search", icon: Search, key: "search" },
    { href: "/all-archive", label: "All Archive", icon: Archive, key: "all-archive" },
  ] as const;
  return <nav aria-label="Main sections" className="flex h-11 shrink-0 items-stretch gap-1 border-b border-rule-grey/45 bg-white px-4 sm:px-6">
    {links.map(({ href, label, icon: Icon, key }) => <Link key={key} href={href} aria-current={active === key ? "page" : undefined}
      className={`relative inline-flex items-center gap-2 px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brick ${active === key ? "text-brick" : "text-ink/65 hover:text-ink"}`}>
      <Icon aria-hidden="true" className="size-4" strokeWidth={1.8} />{label}
      {active === key ? <span className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-brick" /> : null}
    </Link>)}
  </nav>;
}
