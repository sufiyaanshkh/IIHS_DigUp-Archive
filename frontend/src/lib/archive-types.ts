export type DigUpKind = "screenshot" | "image" | "pdf" | "doc" | "audio" | "video" | "code";
export type SearchKind = Exclude<DigUpKind, "code">;
export type SearchMode = "keyword" | "hybrid";
export type SearchScope = "archive" | "code";
export type ResultKind = "image" | "document" | "video" | "audio" | "screenshot" | "code";

export type SearchHit = {
  id: string;
  name: string;
  folder: string;
  kind: ResultKind;
  engine_kind: DigUpKind;
  segment: string;
  location: string | null;
  loc: number | null;
  loc_end: number | null;
  score: number;
  excerpt: string | null;
  metadata: Record<string, string>;
  modified: number;
  size: number;
  mime_type: string;
  preview_url: string | null;
  download_url: string;
  reason: string;
};

export type SearchResponse = {
  query: string;
  mode: SearchMode;
  meaning: boolean;
  strong: number;
  timings_ms: Record<string, number>;
  warning: string | null;
  total: number;
  hits: SearchHit[];
};

export type ArchiveResult = SearchHit & { details: string };
export type ResultFilter = "all" | "screenshot" | "image" | "document" | "video" | "audio";

export type EngineStatus = {
  search_service: string;
  encoder: string;
  vectors: number;
  code_vectors?: number;
  code_files?: number;
  files: number;
  searchable: number;
  pending: number;
  unfinished: number;
  models_available: boolean;
  indexing: IndexingStatus;
};

export type IndexEvent = { event: string; [key: string]: string | number | boolean | undefined };
export type IndexedFileEvent = {
  name: string;
  kind?: string;
  state?: string;
  seconds?: number;
  note?: string;
};

export type IndexingStatus = {
  state: "idle" | "starting" | "scanning" | "indexing" | "waiting" | "completed" | "stopping" | "stopped" | "failed";
  job_id: string | null;
  started_at?: number;
  finished_at?: number;
  checked?: number;
  done?: number;
  total?: number;
  files?: IndexedFileEvent[];
  events?: IndexEvent[];
  error?: string | null;
  search_reload?: string;
  summary_available?: boolean;
  roots?: Array<{
    source: string;
    missing: boolean;
    unreadable: boolean;
    files: number;
    indexed: number;
    pending: number;
    failed: number;
    skipped: number;
    unfinished: number;
    kinds: Record<string, number>;
  }>;
  code_roots?: IndexingStatus["roots"];
};

export type MediaMetadata = {
  name: string;
  kind: string;
  segment: string;
  location: number | string | null;
  location_end: number | string | null;
  modified: number | null;
  size: number | null;
  metadata: Record<string, string>;
  excerpt: string | null;
  source_relative_path: string | null;
  current_size: number | null;
};

export type ImageMetadata = {
  camera: string | null;
  lens: string | null;
  aperture: string | null;
  iso: string | null;
  shutter_speed: string | null;
  white_balance: string | null;
  exposure_compensation: string | null;
  location: string | null;
  capture_time: string | null;
  dimensions: string | null;
};

export const resultKinds = [
  { id: "all", label: "All" },
  { id: "screenshot", label: "Screenshots" },
  { id: "image", label: "Images" },
  { id: "document", label: "Documents" },
  { id: "video", label: "Video" },
  { id: "audio", label: "Audio" },
] as const;

export function kindsForFilter(filter: ResultFilter): SearchKind[] | null {
  switch (filter) {
    case "all": return null;
    case "document": return ["pdf", "doc"];
    default: return [filter];
  }
}

export function toArchiveResult(hit: SearchHit): ArchiveResult {
  const kind = hit.engine_kind === "pdf" || hit.engine_kind === "doc" ? "Document" : hit.kind;
  const modified = hit.modified ? new Date(hit.modified * 1000).toLocaleDateString() : "Date unavailable";
  const size = hit.size > 0 ? formatBytes(hit.size) : "Size unavailable";
  const preview_url = hit.engine_kind === "pdf" && hit.preview_url && hit.loc === null
    ? `${hit.preview_url}?loc=1`
    : hit.preview_url;
  return { ...hit, preview_url, details: `${kind} · ${modified} · ${size}` };
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}
