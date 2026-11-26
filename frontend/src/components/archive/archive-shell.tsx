"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArchiveToolbar } from "@/components/archive/archive-toolbar";
import { PreviewPane } from "@/components/archive/preview-pane";
import { ResultsGrid } from "@/components/archive/results-grid";
import { ResultFilters } from "@/components/archive/result-filters";
import { StatusBar } from "@/components/archive/status-bar";
import { ArchiveSectionNav } from "@/components/archive/archive-section-nav";
import { archiveApi, ArchiveApiError } from "@/lib/archive-api";
import { kindsForFilter, resultKinds, toArchiveResult, type ArchiveResult, type ResultFilter, type SearchScope } from "@/lib/archive-types";
import { useSearchStore } from "@/store/search-store";
import type { AuthenticatedUser } from "@/lib/server-session";

export function ArchiveShell({ user }: { user: AuthenticatedUser }) {
  const query = useSearchStore((state) => state.query);
  const mode = useSearchStore((state) => state.mode);
  const setQuery = useSearchStore((state) => state.setQuery);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<ResultFilter>("all");
  const [scope, setScope] = useState<SearchScope>("archive");
  const [selected, setSelected] = useState<ArchiveResult["id"] | null>(null);
  const [previewOpen, setPreviewOpen] = useState(true);
  const [compactDetails, setCompactDetails] = useState(false);
  const [expandedWeakerKey, setExpandedWeakerKey] = useState<string | null>(null);
  const resultsRef = useRef<HTMLElement>(null);
  const detailsRef = useRef<HTMLDivElement>(null);
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [resultLimit, setResultLimit] = useState(100);
  const previousIndexState = useRef<string | undefined>(undefined);
  const canManageArchive = ["SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"].includes(user.role);
  const typedQuery = query.trim();
  const codePrefix = canManageArchive && /^code:/i.test(typedQuery);
  const effectiveScope = scope === "code" || codePrefix ? "code" : "archive";
  const searchQuery = codePrefix ? typedQuery.replace(/^code:\s*/i, "").trim() : typedQuery;
  const weakerKey = JSON.stringify([typedQuery, mode, effectiveScope, filter, resultLimit]);
  const showWeaker = expandedWeakerKey === weakerKey;

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(typedQuery), 120);
    return () => window.clearTimeout(timer);
  }, [typedQuery]);

  const health = useQuery({ queryKey: ["archive-health"], queryFn: archiveApi.health, refetchInterval: 10_000 });
  const engine = useQuery({ queryKey: ["archive-engine"], queryFn: archiveApi.engineStatus, enabled: health.data?.digup_cli_available === true, refetchInterval: 30_000, retry: 1 });
  const indexing = useQuery({
    queryKey: ["archive-indexing"], queryFn: archiveApi.indexingStatus,
    enabled: canManageArchive && health.data?.digup_cli_available === true,
    refetchInterval: (state) => ["starting", "scanning", "indexing", "waiting", "stopping"].includes(state.state.data?.state ?? "") ? 1_500 : 15_000,
  });
  useEffect(() => {
    const current = indexing.data?.state;
    const previous = previousIndexState.current;
    if (current && ["completed", "failed", "stopped"].includes(current) && ["starting", "scanning", "indexing", "waiting", "stopping"].includes(previous ?? "")) {
      void queryClient.invalidateQueries({ queryKey: ["archive-search"] });
      void queryClient.invalidateQueries({ queryKey: ["archive-engine"] });
    }
    previousIndexState.current = current;
  }, [indexing.data?.state, queryClient]);
  const searchEnabled = searchQuery.length > 0 && searchQuery.length <= 500 && health.data?.digup_cli_available === true;
  const settled = typedQuery === debouncedQuery;
  const prefixAll = useQuery({
    queryKey: ["archive-search", searchQuery, "prefix", effectiveScope, resultLimit],
    queryFn: ({ signal }) => archiveApi.search(searchQuery, "keyword", effectiveScope, null, resultLimit, true, signal),
    enabled: searchEnabled,
    retry: false,
  });
  const prefixFiltered = useQuery({
    queryKey: ["archive-search", searchQuery, "prefix", effectiveScope, resultLimit, filter],
    queryFn: ({ signal }) => archiveApi.search(searchQuery, "keyword", "archive", kindsForFilter(filter), resultLimit, true, signal),
    enabled: searchEnabled && effectiveScope === "archive" && filter !== "all",
    retry: false,
  });
  const finalAll = useQuery({
    queryKey: ["archive-search", searchQuery, mode, effectiveScope, resultLimit],
    queryFn: ({ signal }) => archiveApi.search(searchQuery, mode, effectiveScope, null, resultLimit, false, signal),
    enabled: searchEnabled && settled,
    retry: false,
  });
  const finalFiltered = useQuery({
    queryKey: ["archive-search", searchQuery, mode, effectiveScope, resultLimit, filter],
    queryFn: ({ signal }) => archiveApi.search(searchQuery, mode, "archive", kindsForFilter(filter), resultLimit, false, signal),
    enabled: searchEnabled && settled && effectiveScope === "archive" && filter !== "all",
    retry: false,
  });
  const filtered = effectiveScope === "archive" && filter !== "all";
  const prefixSearch = filtered ? prefixFiltered : prefixAll;
  const finalSearch = filtered ? finalFiltered : finalAll;
  const finalShown = settled && (finalSearch.data !== undefined || finalSearch.isError);
  const search = finalShown ? finalSearch : prefixSearch;
  const allSearch = settled && (finalAll.data !== undefined || finalAll.isError) ? finalAll : prefixAll;
  const startIndexing = useMutation({
    mutationFn: archiveApi.startIndexing,
    onSuccess: (status) => { queryClient.setQueryData(["archive-indexing"], status); void queryClient.invalidateQueries({ queryKey: ["archive-indexing"] }); },
  });
  const stopIndexing = useMutation({
    mutationFn: archiveApi.stopIndexing,
    onSuccess: (status) => { queryClient.setQueryData(["archive-indexing"], status); void queryClient.invalidateQueries({ queryKey: ["archive-indexing"] }); },
  });
  const setBackfill = useMutation({
    mutationFn: archiveApi.setBackfill,
    onSuccess: (status) => { queryClient.setQueryData(["archive-indexing"], status); void queryClient.invalidateQueries({ queryKey: ["archive-indexing"] }); },
  });
  const prewarm = useMutation({
    mutationFn: archiveApi.prewarm,
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["archive-engine"] }); },
  });
  const reloadSearch = useMutation({
    mutationFn: archiveApi.reloadSearch,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["archive-engine"] });
      void queryClient.invalidateQueries({ queryKey: ["archive-indexing"] });
      void queryClient.invalidateQueries({ queryKey: ["archive-search"] });
    },
  });

  const allStrongResults = allSearch.isError ? [] : allSearch.data?.hits.slice(0, allSearch.data.strong) ?? [];
  const allShownResults = useMemo(() => search.data?.hits.map(toArchiveResult) ?? [], [search.data]);
  const strongCount = Math.min(search.data?.strong ?? 0, allShownResults.length);
  const weakerCount = allShownResults.length - strongCount;
  const results = showWeaker ? allShownResults : allShownResults.slice(0, strongCount);
  const selectedResult = results.find((result) => result.id === selected) ?? results[0];
  const metadata = useQuery({
    queryKey: ["archive-media", selectedResult?.id],
    queryFn: () => archiveApi.mediaMetadata(selectedResult!.id),
    enabled: Boolean(selectedResult),
    retry: false,
  });
  const imageMetadata = useQuery({
    queryKey: ["archive-image-metadata", selectedResult?.id],
    queryFn: () => archiveApi.imageMetadata(selectedResult!.id),
    enabled: selectedResult?.kind === "image" || selectedResult?.kind === "screenshot" || selectedResult?.kind === "video",
    retry: false,
  });
  const counts = Object.fromEntries(resultKinds.map(({ id }) => [id,
    id === "all" ? allStrongResults.length : allStrongResults.filter((result) => result.kind === id).length,
  ])) as Record<ResultFilter, number>;
  const searchError = search.error instanceof ArchiveApiError
    ? (search.error.status === 404 ? "Search result expired. Search again." : search.error.message)
    : search.error instanceof Error ? search.error.message : null;
  const countsError = effectiveScope === "archive" && filter !== "all" && allSearch.isError
    ? "Filter counts are unavailable." : null;
  const indexingError = [startIndexing.error, stopIndexing.error, setBackfill.error].find(Boolean);
  const indexingErrorText = indexingError instanceof Error ? indexingError.message : null;
  const engineError = [prewarm.error, reloadSearch.error].find(Boolean);
  const engineReady = health.data?.status === "ok" && health.data.digup_cli_available;
  const indexedFiles = engine.data?.files ?? indexing.data?.roots?.reduce((sum, root) => sum + root.indexed, 0) ?? 0;
  const metadataErrorText = metadata.error instanceof ArchiveApiError
    ? metadata.error.status === 404 ? "This result link has expired. Search again to refresh it." : metadata.error.message
    : metadata.error instanceof Error ? metadata.error.message : null;

  return (
    <main className="bg-sand-deep/70 p-2 sm:p-3">
      <section className="flex h-[calc(100dvh-16px)] w-full flex-col overflow-hidden rounded-xl border border-rule-grey/70 bg-white shadow-[0_18px_60px_rgba(34,34,34,0.14)] sm:h-[calc(100dvh-24px)]" aria-label="IIHS Media Archive search window">
        <ArchiveToolbar
          canManageArchive={canManageArchive}
          canManageUsers={user.role === "SUPER_ADMIN" || user.role === "ADMIN"}
          scope={effectiveScope}
          resultLimit={resultLimit}
          onResultLimitChange={setResultLimit}
          onScopeChange={(value) => {
            if (value === "archive" && /^code:/i.test(query.trim())) setQuery(query.trim().replace(/^code:\s*/i, ""));
            setScope(value);
            setFilter("all");
            setSelected(null);
          }}
          previewOpen={previewOpen}
          onPreviewToggle={() => setPreviewOpen((open) => !open)}
          compactDetails={Boolean(compactDetails && previewOpen && selectedResult)}
          hasSelection={Boolean(selectedResult)}
          onCompactPreviewToggle={() => {
            if (compactDetails && previewOpen) {
              setCompactDetails(false);
              requestAnimationFrame(() => resultsRef.current?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')?.focus());
            } else {
              setPreviewOpen(true);
              setCompactDetails(true);
              requestAnimationFrame(() => detailsRef.current?.focus());
            }
          }}
          engine={engine.data}
          engineLoading={engine.isLoading || health.isLoading}
          engineBusy={prewarm.isPending || reloadSearch.isPending}
          engineError={engineError instanceof Error ? engineError.message : null}
          prewarmState={prewarm.data?.encoder}
          onPrewarm={() => prewarm.mutate()}
          onReloadSearch={() => reloadSearch.mutate()}
          indexing={indexing.data}
          indexingLoading={indexing.isLoading}
          indexingError={indexingErrorText}
          onStartIndexing={() => startIndexing.mutate()}
          onStopIndexing={() => stopIndexing.mutate()}
          onBackfillChange={(enabled) => setBackfill.mutate(enabled)}
          indexingBusy={startIndexing.isPending || stopIndexing.isPending || setBackfill.isPending}
        />
        <ArchiveSectionNav active="search" />
        {effectiveScope === "code" ? <div className="shrink-0 border-b border-rule-grey/40 px-4 py-3 text-sm text-ink/70">Searching the separate code index. Configure code folders in Settings and index them separately.</div> : <ResultFilters active={filter} counts={counts} limit={resultLimit} onChange={setFilter} />}
        {search.data?.warning || (finalShown && mode === "hybrid" && search.data && !search.data.meaning) ? <p role="status" className="shrink-0 border-b border-rule-grey/40 px-4 py-2 text-sm text-brick">{search.data?.warning ?? "Meaning search was not used; showing keyword results."}</p> : null}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <section ref={resultsRef} aria-label="Search results" className={`${compactDetails && previewOpen && selectedResult ? "hidden xl:block" : ""} min-h-0 min-w-0 flex-1 overflow-auto`}>
            {results.length || !weakerCount ? <ResultsGrid results={results} selectedId={selectedResult?.id ?? ""} onSelect={(result) => {
              setSelected(result.id);
              setPreviewOpen(true);
              setCompactDetails(true);
              if (window.matchMedia("(max-width: 1279px)").matches) requestAnimationFrame(() => detailsRef.current?.focus());
            }} onNavigate={(result) => { setSelected(result.id); setPreviewOpen(true); }} query={typedQuery} loading={search.isFetching || (settled && finalSearch.isFetching)} error={searchError}
              showExamples={effectiveScope === "archive"} onExample={setQuery} /> : null}
            {weakerCount > 0 && !searchError ? <button type="button" aria-expanded={showWeaker}
              onClick={() => setExpandedWeakerKey(showWeaker ? null : weakerKey)}
              className="mx-4 mb-4 rounded-md px-2 py-1 text-sm font-medium text-brick focus-visible:outline-2 focus-visible:outline-brick sm:mx-6">
              {showWeaker ? "Hide weaker matches" : `Show ${weakerCount} weaker ${weakerCount === 1 ? "match" : "matches"}`}
            </button> : null}
          </section>
          {previewOpen && selectedResult ? <div ref={detailsRef} role="region" aria-label="Selected result details" tabIndex={-1} className={`${compactDetails ? "flex" : "hidden"} min-h-0 w-full flex-col overflow-auto focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brick xl:flex xl:w-[clamp(352px,27vw,512px)] xl:shrink-0`}>
            <button type="button" className="min-h-11 border-b border-rule-grey/40 px-5 text-left text-sm font-medium text-brick focus-visible:outline-2 focus-visible:outline-brick xl:hidden" onClick={() => {
              setCompactDetails(false);
              requestAnimationFrame(() => resultsRef.current?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]')?.focus());
            }}>← Back to results</button>
            <PreviewPane key={selectedResult.id} result={selectedResult} metadata={metadata.data} metadataLoading={metadata.isLoading} metadataError={metadataErrorText} imageMetadata={imageMetadata.data} imageMetadataLoading={imageMetadata.isLoading} imageMetadataError={imageMetadata.error instanceof Error ? imageMetadata.error.message : null} />
          </div> : null}
        </div>
        <StatusBar resultCount={allShownResults.length} query={typedQuery} engineReady={Boolean(engineReady)} backendUnavailable={health.isError || (health.isSuccess && !health.data.digup_cli_available)} indexedFiles={indexedFiles} searchError={searchError ?? countsError} />
      </section>
    </main>
  );
}
