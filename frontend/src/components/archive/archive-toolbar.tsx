"use client";

import Image from "next/image";
import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { Activity, PanelRight, Search, Settings, Users, X } from "lucide-react";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { searchSchema, type SearchValues } from "@/lib/search-schema";
import type { EngineStatus, IndexingStatus, SearchScope } from "@/lib/archive-types";
import { useSearchStore } from "@/store/search-store";
import { SessionActions } from "@/components/auth/session-actions";

type Props = {
  canManageArchive: boolean;
  canManageUsers: boolean;
  scope: SearchScope;
  onScopeChange: (scope: SearchScope) => void;
  resultLimit: number;
  onResultLimitChange: (limit: number) => void;
  previewOpen: boolean;
  onPreviewToggle: () => void;
  compactDetails: boolean;
  onCompactPreviewToggle: () => void;
  hasSelection: boolean;
  engine: EngineStatus | undefined;
  engineLoading: boolean;
  indexing: IndexingStatus | undefined;
  indexingLoading: boolean;
  indexingError: string | null;
  onStartIndexing: () => void;
  onStopIndexing: () => void;
  indexingBusy: boolean;
};

export function ArchiveToolbar({ canManageArchive, canManageUsers, scope, onScopeChange, resultLimit, onResultLimitChange, previewOpen, onPreviewToggle, compactDetails, onCompactPreviewToggle, hasSelection, engine, engineLoading, indexing, indexingLoading, indexingError, onStartIndexing, onStopIndexing, indexingBusy }: Props) {
  const query = useSearchStore((state) => state.query);
  const mode = useSearchStore((state) => state.mode);
  const setQuery = useSearchStore((state) => state.setQuery);
  const setMode = useSearchStore((state) => state.setMode);
  const { register, control, setValue, formState: { errors } } = useForm<SearchValues>({
    resolver: zodResolver(searchSchema),
    mode: "onChange",
    defaultValues: { query },
  });
  useEffect(() => setValue("query", query), [query, setValue]);
  const value = useWatch({ control, name: "query" });
  const field = register("query", { onChange: (event) => setQuery(event.target.value) });
  const indexedCounts = indexing?.roots?.reduce((counts, root) => ({
    indexed: counts.indexed + root.indexed,
    pending: counts.pending + root.pending,
    failed: counts.failed + root.failed,
  }), { indexed: 0, pending: 0, failed: 0 });

  return (
    <div className="shrink-0 border-b border-rule-grey/50 bg-white">
      <div className="flex min-h-[68px] flex-wrap items-center gap-2 px-4 py-2 sm:gap-3 sm:px-6">
        <div className="flex shrink-0 items-center gap-2 border-r border-rule-grey/40 pr-3 sm:gap-2.5 sm:pr-4">
          <Image src="/IIHS-logo.svg" alt="IIHS" width={37} height={26} className="h-[25px] w-auto" priority />
          <span className="hidden whitespace-nowrap text-sm font-semibold text-ink sm:inline">Media Archive</span>
        </div>
        <label className="order-last flex h-11 min-w-0 basis-full items-center gap-2.5 rounded-lg border border-rule-grey/60 bg-sand-light px-3 text-ink focus-within:border-brick/70 focus-within:ring-2 focus-within:ring-brick/10 sm:order-none sm:flex-1 sm:basis-auto">
          <Search aria-hidden="true" className="size-[17px] shrink-0 text-brick" strokeWidth={1.8} />
          <input
            {...field}
            ref={(element) => field.ref(element)}
            aria-label="Search the archive"
            aria-invalid={Boolean(errors.query)}
            aria-describedby={errors.query ? "search-error" : undefined}
            placeholder="Describe it: ‘a dog on the beach’, ‘the clause about pets’…"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink/45 sm:text-[15px]"
          />
          {value ? (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => {
                setValue("query", "");
                setQuery("");
              }}
              className="grid size-7 shrink-0 place-items-center rounded-full text-ink/50 hover:bg-sand-deep/60 hover:text-ink"
            >
              <X aria-hidden="true" className="size-4" />
            </button>
          ) : null}
          <span className="h-5 border-l border-rule-grey/45" aria-hidden="true" />
          <select
            aria-label="Search mode"
            value={mode}
            onChange={(event) => setMode(event.target.value as "keyword" | "hybrid")}
            className="shrink-0 bg-transparent text-sm text-ink/80 focus-visible:outline-2 focus-visible:outline-brick"
          >
            <option value="hybrid">Hybrid</option>
            <option value="keyword">Keyword</option>
          </select>
        </label>
        {canManageArchive ? <select aria-label="Search scope" value={scope}
          onChange={(event) => onScopeChange(event.target.value as SearchScope)}
          className="h-10 rounded-md border border-rule-grey/60 bg-white px-2 text-sm text-ink/80 focus-visible:outline-2 focus-visible:outline-brick">
          <option value="archive">Archive</option>
          <option value="code">Code</option>
        </select> : null}
        <select aria-label="Maximum search results" value={resultLimit}
          onChange={(event) => onResultLimitChange(Number(event.target.value))}
          className="h-10 rounded-md border border-rule-grey/60 bg-white px-2 text-sm text-ink/80 focus-visible:outline-2 focus-visible:outline-brick">
          <option value={20}>20 results</option>
          <option value={50}>50 results</option>
          <option value={100}>100 results</option>
        </select>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={previewOpen ? "Hide preview" : "Show preview"}
          aria-pressed={previewOpen}
          onClick={onPreviewToggle}
          className={`hidden xl:inline-flex ${previewOpen ? "text-brick" : "text-ink/65"}`}
        >
          <PanelRight aria-hidden="true" className="size-[18px]" strokeWidth={1.8} />
        </Button>
        <Button type="button" variant="ghost" size="icon" disabled={!hasSelection}
          aria-label={compactDetails ? "Show results" : "Show preview"} aria-pressed={compactDetails}
          onClick={onCompactPreviewToggle} className={`xl:hidden ${compactDetails ? "text-brick" : "text-ink/65"}`}>
          <PanelRight aria-hidden="true" className="size-[18px]" strokeWidth={1.8} />
        </Button>
        {canManageArchive ? <details className="relative shrink-0">
          <summary aria-label="Engine and indexing controls" className="grid size-10 cursor-pointer list-none place-items-center rounded-md text-ink/65 hover:bg-sand-deep/50 focus-visible:outline-2 focus-visible:outline-brick [&::-webkit-details-marker]:hidden">
            <Activity aria-hidden="true" className="size-[18px]" strokeWidth={1.8} />
          </summary>
          <section role="region" aria-label="Engine and indexing" className="fixed left-4 right-4 top-16 z-20 max-h-[calc(100dvh-5rem)] overflow-auto rounded-lg border border-rule-grey/50 bg-white p-4 shadow-[0_12px_36px_rgba(34,34,34,0.18)] sm:absolute sm:left-auto sm:right-0 sm:top-12 sm:w-[min(360px,calc(100vw-32px))]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-sm font-semibold text-ink">Archive engine</h2>
                <p className="mt-1 text-xs text-ink/60">{engineLoading ? "Checking DigUp…" : engine ? `${engine.files} files · ${engine.vectors} vectors · ${engine.encoder}` : "Backend status unavailable"}</p>
              </div>
              <span className={`mt-1 size-2 shrink-0 rounded-full ${engine ? "bg-emerald-600" : "bg-rule-grey"}`} aria-label={engine ? "Connected" : "Disconnected"} />
            </div>
            <div className="mt-4 border-t border-rule-grey/35 pt-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-medium capitalize text-ink">{indexingLoading ? "Checking indexing…" : indexing?.state ?? "Index status unavailable"}</p>
                  {indexedCounts ? <p className="mt-1 text-xs text-ink/70">{indexedCounts.indexed} indexed · {indexedCounts.pending} pending · {indexedCounts.failed} failed{indexing?.total ? ` · ${indexing.done ?? 0}/${indexing.total} processed` : ""}</p> : null}
                </div>
                {indexing?.state === "starting" || indexing?.state === "scanning" || indexing?.state === "indexing" || indexing?.state === "waiting" || indexing?.state === "stopping" ? (
                  <Button type="button" variant="outline" size="small" disabled={indexingBusy || indexing?.state === "stopping"} onClick={onStopIndexing}>Stop</Button>
                ) : (
                  <Button type="button" size="small" disabled={indexingBusy || !engine} onClick={onStartIndexing}>Index sources</Button>
                )}
              </div>
              {indexingError ? <p role="alert" className="mt-2 text-xs text-brick">{indexingError}</p> : null}
              {indexing?.error ? <p role="alert" className="mt-2 text-xs text-brick">{indexing.error}</p> : null}
              {indexing?.files?.length ? <ul aria-label="Recent indexing events" className="mt-3 max-h-36 space-y-1 overflow-auto border-t border-rule-grey/35 pt-2 text-[11px] text-ink/65">{indexing.files.slice(-6).reverse().map((file, index) => <li key={`${file.name}-${index}`} className="flex justify-between gap-2"><span className="truncate">{file.name}</span><span className="shrink-0">{file.state ?? file.kind ?? "processed"}</span></li>)}</ul> : null}
              <p className="mt-3 text-xs leading-5 text-ink/70">Indexes the folders selected in Settings. Browser file uploads are not available.</p>
            </div>
          </section>
        </details> : null}
        {canManageArchive ? <Link href="/settings" aria-label="Settings" className="grid size-10 shrink-0 place-items-center rounded-md text-ink/65 hover:bg-sand-deep/50 hover:text-brick focus-visible:outline-2 focus-visible:outline-brick">
          <Settings aria-hidden="true" className="size-[18px]" strokeWidth={1.8} />
        </Link> : null}
        {canManageUsers ? <Link href="/admin" aria-label="Administration" className="grid size-10 shrink-0 place-items-center rounded-md text-ink/65 hover:bg-sand-deep/50 hover:text-brick focus-visible:outline-2 focus-visible:outline-brick">
          <Users aria-hidden="true" className="size-[18px]" strokeWidth={1.8} />
        </Link> : null}
        <SessionActions />
      </div>
      {errors.query ? <p id="search-error" role="alert" className="px-4 pb-2 text-xs text-brick sm:px-6">{errors.query.message}</p> : null}
      <p className="sr-only" aria-live="polite">Search updates against the configured DigUp archive.</p>
    </div>
  );
}
