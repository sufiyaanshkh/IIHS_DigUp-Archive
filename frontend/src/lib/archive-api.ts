import type { EngineStatus, ImageMetadata, IndexingStatus, MediaMetadata, SearchKind, SearchMode, SearchResponse, SearchScope } from "@/lib/archive-types";
import { authApi } from "@/lib/auth-api";

async function request<T>(path: string, init?: RequestInit, csrf = false): Promise<T> {
  const csrfHeaders = csrf ? await authApi.csrfHeaders() : {};
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { Accept: "application/json", ...init?.headers, ...csrfHeaders },
  });
  if (response.status === 401 && typeof window !== "undefined") window.location.assign("/");
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json() as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch { /* Keep the HTTP status as the useful fallback. */ }
    throw new ArchiveApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

export class ArchiveApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ArchiveApiError";
  }
}

export const archiveApi = {
  health: () => request<{ status: string; digup_cli_available: boolean; models_available: boolean; search_service_running: boolean; index_job_state: string }>("/api/health"),
  engineStatus: () => request<EngineStatus>("/api/engine/status"),
  search: (query: string, mode: SearchMode, scope: SearchScope = "archive", kinds: SearchKind[] | null = null, limit = 100) => request<SearchResponse>("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, scope, kinds, limit }),
  }),
  indexingStatus: () => request<IndexingStatus>("/api/indexing/status"),
  startIndexing: () => request<IndexingStatus>("/api/indexing/sync", { method: "POST" }, true),
  stopIndexing: () => request<IndexingStatus>("/api/indexing/stop", { method: "POST" }, true),
  mediaMetadata: (handle: string) => request<MediaMetadata>(`/api/media/${encodeURIComponent(handle)}`),
  imageMetadata: (handle: string) => request<ImageMetadata>(`/api/media/${encodeURIComponent(handle)}/image-metadata`),
  mediaStreamUrl: (handle: string) => `/api/media/${encodeURIComponent(handle)}/stream`,
};
