import type { BrowseResult, SettingsData, StorageInfo, StorageVolume } from "@/lib/settings-types";
import { ArchiveApiError } from "@/lib/archive-api";
import { authApi } from "@/lib/auth-api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const csrfHeaders = method !== "GET" && method !== "HEAD" ? await authApi.csrfHeaders() : {};
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
    } catch { /* Use the status when the response is not JSON. */ }
    throw new ArchiveApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const settingsApi = {
  all: () => request<SettingsData>("/api/settings"),
  code: () => request<SettingsData["code"]>("/api/settings/code"),
  storage: () => request<StorageInfo>("/api/settings/storage"),
  volumes: () => request<{ volumes: StorageVolume[] }>("/api/settings/volumes"),
  browse: (query: { volume_ref?: string; directory_ref?: string; root_id?: string; section?: "folders" | "code" }) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value) params.set(key, value);
    return request<BrowseResult>(`/api/settings/browse?${params.toString()}`);
  },
  addNativeRoots: () => request<{ cancelled: boolean; folders: SettingsData["folders"] }>(
    "/api/settings/folders/native-roots", { method: "POST" },
  ),
  addRoot: (section: "folders" | "code", directory_ref: string) => request<SettingsData["folders"] | SettingsData["code"]>(
    `/api/settings/${section}/roots`, json({ directory_ref }),
  ),
  removeRoot: (section: "folders" | "code", id: string) => request<SettingsData["folders"] | SettingsData["code"]>(
    `/api/settings/${section}/roots/${encodeURIComponent(id)}`, { method: "DELETE" },
  ),
  addExclusion: (section: "folders" | "code", directory_ref: string) => request<SettingsData["folders"] | SettingsData["code"]>(
    `/api/settings/${section}/exclusions`, json({ directory_ref }),
  ),
  removeExclusion: (section: "folders" | "code", id: string) => request<SettingsData["folders"] | SettingsData["code"]>(
    `/api/settings/${section}/exclusions/${encodeURIComponent(id)}`, { method: "DELETE" },
  ),
  extensions: (extensions: string[]) => request<SettingsData["folders"]>(
    "/api/settings/folders/extensions", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ extensions }) },
  ),
};
