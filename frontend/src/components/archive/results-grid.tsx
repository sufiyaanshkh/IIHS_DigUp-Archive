"use client";

import Image from "next/image";
import { AudioLines, Code2, FileText, Image as ImageIcon, Search, Video } from "lucide-react";
import type { ArchiveResult } from "@/lib/archive-types";

type Props = {
  results: ArchiveResult[];
  selectedId: string;
  onSelect: (result: ArchiveResult) => void;
  onNavigate: (result: ArchiveResult) => void;
  query: string;
  loading: boolean;
  error: string | null;
};

const kindIcon = {
  image: ImageIcon,
  document: FileText,
  video: Video,
  audio: AudioLines,
  screenshot: ImageIcon,
  code: Code2,
};

export function ResultsGrid({ results, selectedId, onSelect, onNavigate, query, loading, error }: Props) {
  if (loading && !results.length) {
    return <div className="flex min-h-full items-center justify-center px-6 text-sm text-ink/55" role="status">Searching the archive…</div>;
  }
  if (error) {
    return <div className="flex min-h-full flex-col items-center justify-center px-6 text-center" role="alert"><SearchEmptyIcon /><h2 className="mt-4 text-base font-semibold text-ink">Search is unavailable</h2><p className="mt-1 max-w-sm text-sm text-ink/60">{error}</p></div>;
  }
  if (!results.length) {
    return (
      <div className="flex min-h-full flex-col items-center justify-center px-6 text-center">
        <SearchEmptyIcon />
        <h2 className="mt-4 text-base font-semibold text-ink">{query ? "No matching files" : "Search your archive"}</h2>
        <p className="mt-1 max-w-sm text-sm text-ink/60">{query ? "Try another description or choose a different file type." : "Describe an image, document, recording, or words you remember."}</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 p-4 sm:grid-cols-[repeat(auto-fill,minmax(220px,1fr))] sm:gap-5 sm:p-6">
      {results.map((result, index) => {
        const Icon = kindIcon[result.kind];
        const selected = result.id === selectedId;
        return (
          <button
            key={result.id}
            type="button"
            aria-pressed={selected}
            aria-label={`${result.name}, ${result.folder}, DigUp ranking score ${result.score}`}
            title={`DigUp ranking score: ${result.score}`}
            onClick={() => onSelect(result)}
            onKeyDown={(event) => {
              const delta = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
                : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
              if (!delta) return;
              event.preventDefault();
              const next = Math.max(0, Math.min(results.length - 1, index + delta));
              onNavigate(results[next]);
              const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button[data-result]");
              buttons?.[next]?.focus();
            }}
            data-result
            className={`group min-w-0 rounded-lg p-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brick ${selected ? "bg-warm-sand ring-2 ring-brick" : "hover:bg-sand-deep/35"}`}
          >
            <div className="relative aspect-[4/3] overflow-hidden rounded-md bg-sand-deep/40">
              {result.preview_url ? (
                <Image
                  src={result.preview_url}
                  alt=""
                  fill
                  sizes="(max-width: 640px) 90vw, (max-width: 1280px) 35vw, 260px"
                  unoptimized
                  className="object-cover transition-transform duration-200 group-hover:scale-[1.02] motion-reduce:transition-none motion-reduce:group-hover:scale-100"
                />
              ) : (
                <div className="grid h-full place-items-center text-brick/75">
                  <Icon aria-hidden="true" className="size-10" strokeWidth={1.3} />
                </div>
              )}
              {result.kind !== "image" && result.kind !== "screenshot" ? (
                <span className="absolute left-2 top-2 grid size-6 place-items-center rounded-full bg-ink/65 text-white">
                  <Icon aria-hidden="true" className="size-3.5" />
                </span>
              ) : null}
              {result.location ? <span className="absolute bottom-2 right-2 rounded-full bg-ink/70 px-2 py-0.5 font-mono text-[10px] text-white">{result.location}</span> : null}
            </div>
            <div className="min-w-0 px-1 pt-2">
              <p title={result.name} className="truncate text-sm font-semibold text-ink">{result.name}</p>
              <p title={result.folder} className="truncate text-sm text-ink/70">{result.folder}</p>
            </div>
          </button>
        );
      })}
    </div>
  );
}

function SearchEmptyIcon() {
  return <Search aria-hidden="true" className="size-8 text-brick/60" strokeWidth={1.4} />;
}
