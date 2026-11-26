"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Archive, AudioLines, ChevronLeft, ChevronRight, FileText, Grid2X2, Image as ImageIcon, List, RefreshCw, Search, Settings, Users, Video } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArchiveApiError, archiveApi } from "@/lib/archive-api";
import { formatBytes, toArchiveResult, type ArchiveItem, type ImageMetadata, type MediaMetadata, type ResultKind } from "@/lib/archive-types";
import type { AuthenticatedUser } from "@/lib/server-session";
import { ArchiveSectionNav } from "@/components/archive/archive-section-nav";
import { PreviewPane } from "@/components/archive/preview-pane";
import { SessionActions } from "@/components/auth/session-actions";
import { Button } from "@/components/ui/button";

const typeOptions = [
  ["", "All types"], ["image", "Images"], ["screenshot", "Screenshots"],
  ["document", "Documents"], ["video", "Video"], ["audio", "Audio"],
] as const;
const stateOptions = [["", "All indexing states"], ["done", "Indexed"], ["partial", "Partial"], ["pending", "Processing"], ["failed", "Failed"], ["skipped", "Skipped"], ["unindexed", "Not indexed"], ["unknown", "Unknown"]] as const;
const fileIcons: Record<ResultKind, typeof ImageIcon> = { image: ImageIcon, screenshot: ImageIcon, document: FileText, video: Video, audio: AudioLines, code: FileText };

type View = "grid" | "list";
type Props = { user: AuthenticatedUser; initialSourceId: string | null; initialFolder: string };

export function AllArchiveShell({ user, initialSourceId, initialFolder }: Props) {
  const router = useRouter();
  const [sourceId, setSourceId] = useState<string | null>(initialSourceId);
  const [folder, setFolder] = useState(initialFolder);
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [mediaType, setMediaType] = useState("");
  const [state, setState] = useState("");
  const [extension, setExtension] = useState("");
  const [sizeRange, setSizeRange] = useState("");
  const [modifiedAfter, setModifiedAfter] = useState<number | null>(null);
  const [modifiedRange, setModifiedRange] = useState("");
  const [sort, setSort] = useState("name");
  const [direction, setDirection] = useState("asc");
  const [view, setView] = useState<View>("grid");
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const canManage = user.role === "SUPER_ADMIN" || user.role === "ADMIN" || user.role === "ARCHIVE_OPERATOR";
  const canManageUsers = user.role === "SUPER_ADMIN" || user.role === "ADMIN";

  useEffect(() => {
    const timer = window.setTimeout(() => { setQuery(text.trim()); setOffset(0); }, 250);
    return () => window.clearTimeout(timer);
  }, [text]);

  const params = useMemo(() => {
    const value = new URLSearchParams({ folder, limit: "50", offset: String(offset), sort, direction });
    if (sourceId) value.set("source_id", sourceId);
    if (query) value.set("q", query);
    if (mediaType) value.set("media_type", mediaType);
    if (state) value.set("state", state);
    if (extension.trim()) value.set("extension", extension.trim().replace(/^\./, ""));
    if (modifiedAfter != null) value.set("modified_after", String(modifiedAfter));
    if (sizeRange === "small") value.set("max_size", String(1024 * 1024 - 1));
    if (sizeRange === "medium") { value.set("min_size", String(1024 * 1024)); value.set("max_size", String(100 * 1024 * 1024)); }
    if (sizeRange === "large") value.set("min_size", String(100 * 1024 * 1024 + 1));
    return value;
  }, [sourceId, folder, query, mediaType, state, extension, modifiedAfter, sizeRange, sort, direction, offset]);
  const sourceListing = useQuery({
    queryKey: ["all-archive-sources"],
    queryFn: ({ signal }) => archiveApi.browseArchive(new URLSearchParams(), signal),
    retry: false,
  });
  const listing = useQuery({
    queryKey: ["all-archive", params.toString()],
    queryFn: ({ signal }) => archiveApi.browseArchive(params, signal),
    enabled: Boolean(sourceId),
    retry: false,
  });
  useEffect(() => {
    if (sourceId || !sourceListing.isSuccess) return;
    const source = sourceListing.data.sources.find((item) => item.available);
    if (!source) return;
    setSourceId(source.id);
    setFolder(".");
    router.replace(`/all-archive?source=${encodeURIComponent(source.id)}`, { scroll: false });
  }, [router, sourceId, sourceListing.data, sourceListing.isSuccess]);
  const data = listing.data;
  const sources = sourceListing.data?.sources ?? data?.sources ?? [];
  const selected = data?.items.find((item) => item.id === selectedId) ?? null;
  const result = selected ? toArchiveResult(selected) : null;
  const metadata = useQuery({ queryKey: ["archive-media", selected?.id], queryFn: () => archiveApi.mediaMetadata(selected!.id), enabled: Boolean(selected), retry: false });
  const imageMetadata = useQuery({
    queryKey: ["archive-image-metadata", selected?.id], queryFn: () => archiveApi.imageMetadata(selected!.id),
    enabled: ["image", "screenshot", "video"].includes(selected?.kind ?? ""), retry: false,
  });
  const activeFilters = [mediaType, state, extension, sizeRange, modifiedAfter != null, query].filter(Boolean).length;
  const maxPages = data ? Math.ceil(data.total / data.limit) : 0;
  const error = listing.error instanceof ArchiveApiError && listing.error.status === 404
    ? "This source or folder is no longer available. Choose a source again."
    : listing.error instanceof Error ? listing.error.message : "Could not read indexed archive items.";
  const setLocation = (nextSource: string | null, nextFolder = ".") => {
    setSourceId(nextSource); setFolder(nextFolder); setOffset(0); setSelectedId(null);
    const params = new URLSearchParams();
    if (nextSource) params.set("source", nextSource);
    if (nextFolder !== ".") params.set("folder", nextFolder);
    router.push(`/all-archive${params.size ? `?${params.toString()}` : ""}`, { scroll: false });
  };
  const navigateFolder = (nextFolder: string) => {
    setFolder(nextFolder); setOffset(0); setSelectedId(null);
    const params = new URLSearchParams();
    if (sourceId) params.set("source", sourceId);
    if (nextFolder !== ".") params.set("folder", nextFolder);
    router.push(`/all-archive?${params.toString()}`, { scroll: false });
  };
  const clearFilters = () => {
    setText(""); setQuery(""); setMediaType(""); setState(""); setExtension(""); setSizeRange(""); setModifiedAfter(null); setModifiedRange(""); setOffset(0);
  };
  const selectItem = (item: ArchiveItem) => setSelectedId(item.id);

  return <main className="bg-sand-deep/70 p-2 sm:p-3">
    <section aria-label="IIHS Media Archive library" className="flex h-[calc(100dvh-16px)] w-full flex-col overflow-hidden rounded-xl border border-rule-grey/70 bg-white shadow-[0_18px_60px_rgba(34,34,34,0.14)] sm:h-[calc(100dvh-24px)]">
      <header className="flex min-h-[68px] shrink-0 flex-wrap items-center justify-between gap-3 border-b border-rule-grey/50 bg-white px-4 py-2 sm:px-6">
        <div className="flex items-center gap-3 border-r border-rule-grey/40 pr-4">
          <Image src="/IIHS-logo.svg" alt="IIHS" width={37} height={26} className="h-[25px] w-auto" priority />
          <span className="whitespace-nowrap text-sm font-semibold text-ink">Media Archive</span>
        </div>
        <div className="flex min-w-0 items-center gap-1 sm:gap-2">
          {canManage ? <Link href="/settings" aria-label="Settings" title="Settings" className="grid size-9 place-items-center rounded-md text-ink/65 hover:bg-sand-deep/45 focus-visible:outline-2 focus-visible:outline-brick"><Settings className="size-[18px]" /></Link> : null}
          {canManageUsers ? <Link href="/admin" aria-label="User administration" title="User administration" className="grid size-9 place-items-center rounded-md text-ink/65 hover:bg-sand-deep/45 focus-visible:outline-2 focus-visible:outline-brick"><Users className="size-[18px]" /></Link> : null}
          <SessionActions />
        </div>
      </header>
      <ArchiveSectionNav active="all-archive" />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <aside aria-label="Archive sources and folders" className="hidden w-56 shrink-0 flex-col overflow-auto border-r border-rule-grey/40 bg-sand-light/65 p-3 md:flex lg:w-64">
          <p className="px-2 pb-2 text-xs font-semibold text-ink/60">Configured sources</p>
          {sources.map((source) => <button key={source.id} type="button" onClick={() => setLocation(source.id)} disabled={!source.available}
            aria-current={source.id === sourceId && folder === "." ? "page" : undefined}
            className={`mb-1 flex min-h-10 items-center gap-2 rounded-md px-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-brick ${source.id === sourceId ? "bg-warm-sand font-semibold text-brick" : "text-ink hover:bg-sand-deep/40"} disabled:cursor-not-allowed disabled:opacity-50`}>
            <Archive aria-hidden="true" className="size-4 shrink-0" /><span className="min-w-0 flex-1 truncate">{source.name}</span>
          </button>)}
          {sourceListing.isError ? <p className="px-2 text-sm text-ink/65">Could not load archive sources.</p> : sourceListing.isSuccess && !sources.length ? <p className="px-2 text-sm text-ink/65">No archive sources configured.</p> : null}
          {sourceId ? <>
            <div className="my-3 border-t border-rule-grey/35" />
            <button type="button" onClick={() => setLocation(sourceId)} aria-current={folder === "." ? "page" : undefined}
              className="flex min-h-9 items-center gap-2 rounded-md px-2 text-left text-sm font-medium text-ink hover:bg-sand-deep/40 focus-visible:outline-2 focus-visible:outline-brick">
              <Archive className="size-4 text-brick" />All files
            </button>
            {data?.breadcrumbs.slice(1).map((crumb, index) => <button key={crumb.relative_path} type="button"
              onClick={() => navigateFolder(crumb.relative_path)}
              aria-current={crumb.relative_path === folder ? "page" : undefined}
              className="flex min-h-9 items-center gap-2 rounded-md px-2 text-left text-sm text-ink hover:bg-sand-deep/40 focus-visible:outline-2 focus-visible:outline-brick"
              style={{ paddingLeft: `${12 + (index + 1) * 12}px` }}>
              <span className="size-1.5 rounded-full bg-rule-grey" />{crumb.name}
            </button>)}
          {data?.folders.map((child) => <button key={child.relative_path} type="button"
              onClick={() => navigateFolder(child.relative_path)}
              className="flex min-h-9 items-center gap-2 rounded-md px-2 text-left text-sm text-ink hover:bg-sand-deep/40 focus-visible:outline-2 focus-visible:outline-brick"
              style={{ paddingLeft: `${12 + data.breadcrumbs.length * 12}px` }}>
              <span className="size-1.5 rounded-full bg-brick/70" /><span className="min-w-0 flex-1 truncate">{child.name}</span>
              <span className="font-mono text-xs text-ink/55">{child.file_count ?? "—"}</span>
            </button>)}
          </> : null}
          <p className="mt-auto px-2 pt-5 text-xs leading-5 text-ink/55">Files come from configured folders. DigUp indexing is managed separately in Settings.</p>
        </aside>

        <section aria-label="Indexed media" className={`${selected ? "max-xl:hidden" : ""} flex min-w-0 flex-1 flex-col overflow-hidden`}>
          <div className="shrink-0 border-b border-rule-grey/35 px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="min-w-0">
                <nav aria-label="Folder breadcrumbs" className="flex min-w-0 items-center gap-1 overflow-x-auto text-sm">
                  {(data?.breadcrumbs ?? []).map((crumb, index) => <span key={crumb.relative_path} className="inline-flex shrink-0 items-center gap-1">
                    {index ? <ChevronRight aria-hidden="true" className="size-3.5 text-ink/40" /> : null}
                    {index === (data?.breadcrumbs.length ?? 0) - 1 ? <span className="font-semibold text-ink">{crumb.name}</span> :
                      <button type="button" className="text-ink/65 hover:text-brick focus-visible:outline-2 focus-visible:outline-brick" onClick={() => navigateFolder(crumb.relative_path)}>{crumb.name}</button>}
                  </span>)}
                  {!data?.breadcrumbs.length ? <h1 className="font-semibold text-ink">All Archive</h1> : null}
                </nav>
                <p className="mt-1 text-xs text-ink/60">{data ? `${data.total.toLocaleString()} ${data.total === 1 ? "file" : "files"}` : "Browse files in configured source folders"}</p>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" variant="ghost" size="icon" aria-label="Refresh archive" title="Refresh archive" onClick={() => void (sourceId ? listing.refetch() : sourceListing.refetch())}><RefreshCw className={`size-4 ${(sourceId ? listing.isFetching : sourceListing.isFetching) ? "animate-spin" : ""}`} /></Button>
                <div className="flex rounded-md border border-rule-grey/50 p-0.5" aria-label="View mode">
                  <button type="button" aria-label="Grid view" aria-pressed={view === "grid"} onClick={() => setView("grid")} className={`grid size-8 place-items-center rounded-sm focus-visible:outline-2 focus-visible:outline-brick ${view === "grid" ? "bg-warm-sand text-brick" : "text-ink/65 hover:bg-sand-light"}`}><Grid2X2 className="size-4" /></button>
                  <button type="button" aria-label="List view" aria-pressed={view === "list"} onClick={() => setView("list")} className={`grid size-8 place-items-center rounded-sm focus-visible:outline-2 focus-visible:outline-brick ${view === "list" ? "bg-warm-sand text-brick" : "text-ink/65 hover:bg-sand-light"}`}><List className="size-4" /></button>
                </div>
              </div>
            </div>
            <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(180px,1fr)_auto_auto_auto_auto]">
              <label className="flex h-10 min-w-0 items-center gap-2 rounded-md border border-rule-grey/55 bg-sand-light px-3 focus-within:border-brick/70 focus-within:ring-2 focus-within:ring-brick/10">
                <Search aria-hidden="true" className="size-4 shrink-0 text-brick" /><input aria-label="Search within this folder" value={text} onChange={(event) => setText(event.target.value)} placeholder="Search within this folder" className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink/45" />
              </label>
              <select aria-label="Filter media type" value={mediaType} onChange={(event) => { setMediaType(event.target.value); setOffset(0); }} className="h-10 rounded-md border border-rule-grey/55 bg-white px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-brick">{typeOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
              <select aria-label="Filter processing state" value={state} onChange={(event) => { setState(event.target.value); setOffset(0); }} className="h-10 rounded-md border border-rule-grey/55 bg-white px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-brick">{stateOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
              <select aria-label="Filter modified date" value={modifiedRange} onChange={(event) => { const range = event.target.value; setModifiedRange(range); setModifiedAfter(range === "today" ? Math.floor(new Date().setHours(0, 0, 0, 0) / 1000) : range ? Math.floor(Date.now() / 1000) - Number(range) * 86400 : null); setOffset(0); }} className="h-10 rounded-md border border-rule-grey/55 bg-white px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-brick">
                <option value="">Any modified date</option><option value="today">Today</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option>
              </select>
              <div className="flex gap-2">
                <select aria-label="Filter file size" value={sizeRange} onChange={(event) => { setSizeRange(event.target.value); setOffset(0); }} className="h-10 min-w-0 flex-1 rounded-md border border-rule-grey/55 bg-white px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-brick"><option value="">Any size</option><option value="small">Under 1 MB</option><option value="medium">1–100 MB</option><option value="large">Over 100 MB</option></select>
                <input aria-label="Filter extension" value={extension} onChange={(event) => { setExtension(event.target.value); setOffset(0); }} placeholder=".ext" className="h-10 w-20 rounded-md border border-rule-grey/55 bg-white px-2 text-sm outline-none focus-visible:outline-2 focus-visible:outline-brick" />
              </div>
            </div>
            <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <label className="text-xs text-ink/60">Sort</label><select aria-label="Sort archive items" value={`${sort}:${direction}`} onChange={(event) => { const [nextSort, nextDirection] = event.target.value.split(":"); setSort(nextSort); setDirection(nextDirection); setOffset(0); }} className="h-8 rounded border border-rule-grey/45 bg-white px-2 text-xs text-ink"><option value="name:asc">Name A–Z</option><option value="name:desc">Name Z–A</option><option value="modified:desc">Recently modified</option><option value="modified:asc">Oldest modified</option><option value="size:desc">Largest first</option><option value="size:asc">Smallest first</option><option value="state:asc">Processing state</option></select>
              </div>
              {activeFilters ? <button type="button" onClick={clearFilters} className="text-xs font-medium text-brick underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-brick">Clear filters ({activeFilters})</button> : null}
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-auto">
            {sourceId && listing.isLoading ? <div role="status" className="grid h-full place-items-center text-sm text-ink/65">Loading archive files…</div> : sourceId && listing.isError ? <div role="alert" className="grid h-full place-items-center px-6 text-center"><div><h2 className="font-semibold text-ink">Archive listing unavailable</h2><p className="mt-2 max-w-md text-sm text-ink/65">{error}</p><p className="mt-2 text-sm text-ink/65">Choose a configured source from the sidebar to return to its root folder.</p><Button className="mt-4" variant="outline" onClick={() => void listing.refetch()}>Try again</Button></div></div> : !sourceId && sourceListing.isLoading ? <div role="status" className="grid h-full place-items-center text-sm text-ink/65">Loading configured sources…</div> : !sourceId && sourceListing.isError ? <div role="alert" className="grid h-full place-items-center px-6 text-center"><div><h2 className="font-semibold text-ink">Archive sources unavailable</h2><p className="mt-2 text-sm text-ink/65">{sourceListing.error instanceof Error ? sourceListing.error.message : "Could not read configured sources."}</p><Button className="mt-4" variant="outline" onClick={() => void sourceListing.refetch()}>Try again</Button></div></div> : !sourceId ? <div className="grid h-full place-items-center px-6 text-center"><div><Archive className="mx-auto size-9 text-brick/70" /><h2 className="mt-3 font-semibold text-ink">No archive source available</h2><p className="mt-1 max-w-sm text-sm text-ink/65">Configure an available source folder in Settings to browse its files.</p><div className="mt-4 flex flex-wrap justify-center gap-2 md:hidden">{sources.map((source) => <Button key={source.id} type="button" variant="outline" disabled={!source.available} onClick={() => setLocation(source.id)}>{source.name}</Button>)}</div></div></div> : !data || (!data.items.length && !data.folders.length) ? <div className="grid h-full place-items-center px-6 text-center"><div><Archive className="mx-auto size-8 text-brick/65" /><h2 className="mt-3 font-semibold text-ink">{data?.total ? "No files on this page" : query || activeFilters ? "No files match these filters" : "No files in this folder"}</h2><p className="mt-1 text-sm text-ink/65">{query || activeFilters ? "Adjust or clear the filters to see more files." : "This available folder contains no supported files."}</p></div></div> : <>
              {data.folders.length ? <div className="border-b border-rule-grey/30 p-3 sm:p-4"><p className="mb-2 text-xs font-semibold text-ink/60">Folders</p><div className="flex flex-wrap gap-2">{data.folders.map((child) => <button key={child.relative_path} type="button" onClick={() => navigateFolder(child.relative_path)} className="inline-flex max-w-full items-center gap-2 rounded-md border border-rule-grey/45 bg-white px-3 py-2 text-sm text-ink hover:bg-sand-light focus-visible:outline-2 focus-visible:outline-brick"><Archive className="size-4 shrink-0 text-brick" /><span className="truncate">{child.name}</span><span className="font-mono text-xs text-ink/55">{child.file_count ?? "—"}</span></button>)}</div></div> : null}
              {view === "grid" ? <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-[repeat(auto-fill,minmax(190px,1fr))] sm:gap-4 sm:p-4">
                {data.items.map((item) => <ArchiveGridCard key={item.id} item={item} selected={item.id === selectedId} onClick={() => selectItem(item)} />)}
              </div> : <div className="min-w-[760px] p-3 sm:p-4"><div className="grid grid-cols-[minmax(220px,2fr)_minmax(120px,1fr)_minmax(160px,1.4fr)_110px_100px_150px] gap-3 border-b border-rule-grey/40 px-3 py-2 text-xs font-semibold text-ink/60"><span>Name</span><span>Type</span><span>Folder</span><span>Index status</span><span>Size</span><span>Modified</span></div>
                {data.items.map((item) => { const Icon = fileIcons[item.kind]; return <button key={item.id} type="button" aria-pressed={item.id === selectedId} onClick={() => selectItem(item)} className={`grid w-full grid-cols-[minmax(220px,2fr)_minmax(120px,1fr)_minmax(160px,1.4fr)_110px_100px_150px] gap-3 border-b border-rule-grey/25 px-3 py-3 text-left text-sm focus-visible:outline-2 focus-visible:outline-brick ${item.id === selectedId ? "bg-warm-sand/80" : "hover:bg-sand-light/70"}`}><span className="flex min-w-0 items-center gap-2 font-medium text-ink"><Icon className="size-4 shrink-0 text-brick" /><span className="truncate">{item.name}</span></span><span className="capitalize text-ink/70">{item.engine_kind === "pdf" || item.engine_kind === "doc" ? "Document" : item.engine_kind}</span><span className="truncate text-ink/65">{item.folder}</span><span className="text-ink/70">{indexingStateLabel(item.processing_state)}</span><span className="text-ink/70">{formatBytes(item.size)}</span><span className="text-ink/70">{new Date(item.modified * 1000).toLocaleDateString()}</span></button>; })}
              </div>}
            </>}
          </div>
          <footer className="flex min-h-10 shrink-0 items-center justify-between gap-3 border-t border-rule-grey/45 bg-white px-4 text-xs text-ink/70 sm:px-5">
            <span className="truncate">{sources.find((source) => source.id === sourceId)?.location ?? "Configured archive source"}{data?.schema_version ? ` · DigUp index v${data.schema_version} status` : " · Filesystem listing"}</span>
            <div className="flex shrink-0 items-center gap-2"><span className="font-mono tabular-nums">{data?.total ?? 0} items</span><Button type="button" variant="ghost" size="icon" aria-label="Previous page" disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 50)); setSelectedId(null); }}><ChevronLeft className="size-4" /></Button><span>{maxPages ? Math.floor(offset / 50) + 1 : 0} / {maxPages}</span><Button type="button" variant="ghost" size="icon" aria-label="Next page" disabled={!data || offset + data.limit >= data.total} onClick={() => { setOffset(offset + 50); setSelectedId(null); }}><ChevronRight className="size-4" /></Button></div>
          </footer>
        </section>

        {selected && result ? <div className="flex min-h-0 w-full flex-col overflow-auto xl:w-[clamp(352px,27vw,512px)] xl:shrink-0">
          <button type="button" className="min-h-11 border-b border-rule-grey/40 px-5 text-left text-sm font-medium text-brick focus-visible:outline-2 focus-visible:outline-brick xl:hidden" onClick={() => setSelectedId(null)}><ChevronLeft className="mr-1 inline size-4" />Back to archive</button>
          <PreviewPane result={result} metadata={metadata.data as MediaMetadata | undefined} metadataLoading={metadata.isLoading} metadataError={metadata.error instanceof Error ? metadata.error.message : null} imageMetadata={imageMetadata.data as ImageMetadata | undefined} imageMetadataLoading={imageMetadata.isLoading} imageMetadataError={imageMetadata.error instanceof Error ? imageMetadata.error.message : null} />
        </div> : null}
      </div>
    </section>
  </main>;
}

function ArchiveGridCard({ item, selected, onClick }: { item: ArchiveItem; selected: boolean; onClick: () => void }) {
  const Icon = fileIcons[item.kind];
  return <button type="button" aria-pressed={selected} onClick={onClick} className={`group min-w-0 rounded-lg p-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brick ${selected ? "bg-warm-sand ring-2 ring-brick" : "hover:bg-sand-deep/30"}`}>
    <div className="relative aspect-[4/3] overflow-hidden rounded-md border border-rule-grey/25 bg-sand-light">
      {item.preview_url ? <Image src={item.preview_url} alt="" fill sizes="(max-width: 640px) 90vw, (max-width: 1280px) 30vw, 240px" unoptimized className="object-cover transition-transform duration-200 group-hover:scale-[1.02] motion-reduce:transition-none motion-reduce:group-hover:scale-100" /> : <div className="grid h-full place-items-center text-brick/70"><Icon aria-hidden="true" className="size-10" strokeWidth={1.3} /></div>}
      <span className="absolute bottom-2 right-2 rounded-full bg-ink/70 px-2 py-1 font-mono text-[10px] text-white">{formatBytes(item.size)}</span>
      <span className="absolute left-2 top-2 rounded-full bg-white/90 px-2 py-1 text-[10px] text-ink">{indexingStateLabel(item.processing_state)}</span>
    </div>
    <div className="min-w-0 px-1 pt-2"><p title={item.name} className="truncate text-sm font-semibold text-ink">{item.name}</p><p title={item.folder} className="truncate text-sm text-ink/65">{item.folder}</p><p className="mt-1 text-xs text-ink/55">Modified {new Date(item.modified * 1000).toLocaleDateString()}</p></div>
  </button>;
}

function indexingStateLabel(state: ArchiveItem["processing_state"]): string {
  return ({ done: "Indexed", partial: "Partial", pending: "Processing", failed: "Failed",
    skipped: "Skipped", unindexed: "Not indexed", unknown: "Unknown" })[state];
}
