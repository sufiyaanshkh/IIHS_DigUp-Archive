"use client";

import { resultKinds, type ResultFilter } from "@/lib/archive-types";
import { Button } from "@/components/ui/button";

type Props = {
  active: ResultFilter;
  counts: Record<ResultFilter, number>;
  limit: number;
  onChange: (filter: ResultFilter) => void;
};

export function ResultFilters({ active, counts, limit, onChange }: Props) {
  return (
    <nav aria-label="Filter results by file kind" title={`Counts show strong matches among up to ${limit} unfiltered results.`} className="flex shrink-0 flex-wrap items-center gap-1.5 border-b border-rule-grey/40 bg-white px-4 py-2 sm:px-6">
      {resultKinds.map(({ id, label }) => {
        const selected = active === id;
        return (
          <Button
            key={id}
            type="button"
            variant={selected ? "default" : "ghost"}
            size="small"
            aria-pressed={selected}
            onClick={() => onChange(id)}
            className={`min-h-10 shrink-0 gap-1.5 rounded-full px-3 text-sm ${selected ? "" : "text-ink/75"}`}
          >
            <span>{label}</span>
            {id !== "all" && counts[id] > 0 ? <span className={selected ? "opacity-75" : "text-ink/45"}>{counts[id]}</span> : null}
          </Button>
        );
      })}
    </nav>
  );
}
