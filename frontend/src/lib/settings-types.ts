export type ConfiguredFolder = {
  id: string;
  name: string;
  location: string;
  relative_path: string;
  available: boolean;
};

export type GeneralSettings = {
  indexing_behavior: "disabled";
  automatic_indexing_available: boolean;
  desktop_only: Array<{ name: string; desktop_default: string }>;
};

export type FolderSettings = {
  roots: ConfiguredFolder[];
  excluded_folders: ConfiguredFolder[];
  excluded_extensions: string[];
};

export type CodeSettings = {
  roots: ConfiguredFolder[];
  excluded_folders: ConfiguredFolder[];
  indexing_available: boolean;
  search_available: boolean;
  search_note: string;
  editor: { available: boolean; note: string };
  index: { files: number; vectors: number; state: string; roots: NonNullable<import("@/lib/archive-types").IndexingStatus["roots"]> };
};

export type SettingsData = {
  general: GeneralSettings;
  folders: FolderSettings;
  code: CodeSettings;
};

export type StorageInfo = {
  index: {
    location: string;
    database_files: string[];
    size_bytes: number;
    archive_size_bytes: number;
    code_size_bytes: number;
    free_bytes: number | null;
  };
  models: {
    location: string;
    name: string;
    files: Array<{ name: string; available: boolean; size_bytes: number | null; expected_bytes: number }>;
    all_available: boolean;
    runtime_state: string;
    search_service_running: boolean;
  };
};

export type StorageVolume = {
  ref: string;
  name: string;
  kind: "mounted" | "local" | "test";
  available: boolean;
  capacity_bytes: number | null;
  free_bytes: number | null;
};

export type BrowseResult = {
  current: { ref: string; name: string; relative_path: string };
  parent_ref: string | null;
  entries: Array<{ ref: string; name: string; relative_path: string }>;
  truncated: boolean;
};
