"use client";

import Image from "next/image";
import { AudioLines, Code2, FileText, Image as ImageIcon, Search, Video } from "lucide-react";
import { useState } from "react";
import type { ArchiveResult } from "@/lib/archive-types";

type Props = {
  results: ArchiveResult[];
  selectedId: string;
  onSelect: (result: ArchiveResult) => void;
  onNavigate: (result: ArchiveResult) => void;
  query: string;
  loading: boolean;
  error: string | null;
  showExamples: boolean;
  onExample: (query: string) => void;
};

const kindIcon = {
  image: ImageIcon,
  document: FileText,
  video: Video,
  audio: AudioLines,
  screenshot: ImageIcon,
  code: Code2,
};

const examples = [
  { text: "a screenshot of an error message", kind: "screenshot" },
  { text: "receipt", kind: "document" },
  { text: "whiteboard notes", kind: "image" },
  { text: "someone laughing", kind: "audio" },
  { text: "a dog on the beach", kind: "video" },
  { text: "slides about the budget", kind: "document" },
] as const;

export function ResultsGrid({ results, selectedId, onSelect, onNavigate, query, loading, error, showExamples, onExample }: Props) {
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
        {!query && showExamples ? <div className="mt-6 max-w-xl" aria-label="Example searches">
          <p className="text-xs font-medium uppercase text-ink/55">Try</p>
          <div className="mt-2 flex flex-wrap justify-center gap-2">
            {examples.map(({ text, kind }) => {
              const Icon = kindIcon[kind];
              return <button key={text} type="button" onClick={() => onExample(text)}
                className="inline-flex items-center gap-1.5 rounded-full bg-sand-light px-3 py-1.5 text-sm text-ink hover:bg-sand-deep/60 focus-visible:outline-2 focus-visible:outline-brick">
                <Icon aria-hidden="true" className="size-3.5 text-brick" />
                {text}
              </button>;
            })}
          </div>
        </div> : null}
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
              if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing) return;
              const delta = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
                : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
              if (!delta) return;
              event.preventDefault();
              const buttons = Array.from(event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>("button[data-result]") ?? []);
              let next = Math.max(0, Math.min(results.length - 1, index + delta));
              if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                const current = event.currentTarget.getBoundingClientRect();
                const candidates = buttons.map((button, buttonIndex) => ({ index: buttonIndex, rect: button.getBoundingClientRect() }))
                  .filter(({ rect }) => delta > 0 ? rect.top > current.top : rect.top < current.top);
                const row = candidates.reduce<number | null>((nearest, { rect }) =>
                  nearest === null || (delta > 0 ? rect.top < nearest : rect.top > nearest) ? rect.top : nearest, null);
                const nearest = candidates.filter(({ rect }) => rect.top === row)
                  .sort((a, b) => Math.abs(a.rect.left - current.left) - Math.abs(b.rect.left - current.left))[0];
                next = nearest?.index ?? index;
              }
              onNavigate(results[next]);
              buttons[next]?.focus();
            }}
            data-result
            className={`group min-w-0 rounded-lg p-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brick ${selected ? "bg-warm-sand ring-2 ring-brick" : "hover:bg-sand-deep/35"}`}
          >
            <div className="relative aspect-[4/3] overflow-hidden rounded-md bg-sand-deep/40">
              <ResultThumbnail key={result.preview_url ?? ""} result={result} />
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

function ResultThumbnail({ result }: { result: ArchiveResult }) {
  const [failed, setFailed] = useState(false);
  const Icon = kindIcon[result.kind];
  if (result.preview_url && !failed) {
    return <Image
      src={result.preview_url}
      alt=""
      fill
      sizes="(max-width: 640px) 90vw, (max-width: 1280px) 35vw, 260px"
      unoptimized
      onError={() => setFailed(true)}
      className="object-cover transition-transform duration-200 group-hover:scale-[1.02] motion-reduce:transition-none motion-reduce:group-hover:scale-100"
    />;
  }
  return <div className="grid h-full place-items-center text-brick/75">
    <div className="flex flex-col items-center gap-2">
      <Icon aria-hidden="true" className="size-10" strokeWidth={1.3} />
      {failed ? <span role="status" className="text-xs">Preview unavailable</span> : null}
    </div>
  </div>;
}

function SearchEmptyIcon() {
  return <Search aria-hidden="true" className="size-8 text-brick/60" strokeWidth={1.4} />;
}
