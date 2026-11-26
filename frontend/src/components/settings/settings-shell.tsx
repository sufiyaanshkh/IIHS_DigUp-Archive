"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ArrowLeft, ChevronRight, HardDrive, RefreshCw, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { settingsApi } from "@/lib/settings-api";
import { SessionActions } from "@/components/auth/session-actions";
import type { BrowseResult, CodeSettings, ConfiguredFolder, FolderSettings, SettingsData, StorageInfo, StorageVolume } from "@/lib/settings-types";

type Tab = "general" | "folders" | "code" | "storage";
const tabs: Array<{ id: Tab; label: string }> = [
  { id: "general", label: "General" },
  { id: "folders", label: "Folders" },
  { id: "code", label: "Code" },
  { id: "storage", label: "Storage" },
];

function bytes(value: number | null | undefined): string {
  if (value == null) return "Unavailable";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = value / 1024;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unit]}`;
}

export function SettingsShell() {
  const [tab, setTab] = useState<Tab>("general");
  const [data, setData] = useState<SettingsData | null>(null);
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [volumes, setVolumes] = useState<StorageVolume[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [picker, setPicker] = useState<{ section: "folders" | "code"; action: "root" | "exclude"; rootId?: string } | null>(null);

  const loadSettings = useCallback(async () => {
    const [settings, code] = await Promise.all([settingsApi.all(), settingsApi.code()]);
    return { ...settings, code };
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const settings = await loadSettings();
      setData(settings);
      const [locations, storageInfo] = await Promise.allSettled([settingsApi.volumes(), settingsApi.storage()]);
      if (locations.status === "fulfilled") setVolumes(locations.value.volumes);
      if (storageInfo.status === "fulfilled") setStorage(storageInfo.value);
      else setStorage(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Settings could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [loadSettings]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const settings = await loadSettings();
        if (active) setData(settings);
        const [locations, storageInfo] = await Promise.allSettled([settingsApi.volumes(), settingsApi.storage()]);
        if (active && locations.status === "fulfilled") setVolumes(locations.value.volumes);
        if (active) setStorage(storageInfo.status === "fulfilled" ? storageInfo.value : null);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Settings could not be loaded.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [loadSettings]);

  async function change(operation: () => Promise<unknown>, message = "Saved. The next indexing run will use this configuration.") {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await operation();
      const updated = await loadSettings();
      setData(updated);
      setNotice(message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The setting could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function selectDirectory(directoryRef: string) {
    if (!picker) return;
    const current = picker;
    setPicker(null);
    const operation = current.action === "root"
      ? () => settingsApi.addRoot(current.section, directoryRef)
      : () => settingsApi.addExclusion(current.section, directoryRef);
    await change(operation);
  }

  async function selectNativeRoots() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await settingsApi.addNativeRoots();
      if (!result.cancelled) {
        setData((current) => current ? { ...current, folders: result.folders } : current);
        setNotice("Saved. The next indexing run will use this configuration.");
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The native folder chooser could not be opened.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-sand-deep/70 p-1.5 sm:p-4">
      <section className="flex min-h-[calc(100dvh-12px)] w-full flex-col overflow-hidden rounded-[13px] border border-rule-grey/70 bg-white shadow-[0_18px_60px_rgba(34,34,34,0.14)] sm:min-h-[calc(100dvh-32px)]">
        <header className="flex flex-wrap items-center justify-between gap-4 border-b border-rule-grey/45 px-5 py-4 sm:px-8">
          <div>
            <Link href="/archive" className="inline-flex items-center gap-2 text-xs font-medium text-ink/60 transition-colors hover:text-brick">
              <ArrowLeft aria-hidden="true" className="size-4" /> Back to archive
            </Link>
            <h1 className="mt-3 text-xl font-semibold tracking-tight text-ink">Settings</h1>
            <p className="mt-1 text-sm text-ink/70">DigUp sources, indexing preferences, and local storage.</p>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="small" disabled={loading || busy} onClick={() => void refresh()}>
              <RefreshCw aria-hidden="true" className="size-3.5" /> Refresh
            </Button>
            <SessionActions />
          </div>
        </header>

        <div className="border-b border-rule-grey/40 px-4 sm:px-8">
          <div className="flex gap-1 overflow-x-auto" role="tablist" aria-label="Settings sections">
            {tabs.map((item) => (
              <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)}
                className={`min-h-12 shrink-0 border-b-2 px-4 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-brick ${tab === item.id ? "border-brick font-semibold text-brick" : "border-transparent text-ink/60 hover:text-ink"}`}>
                {item.label}
              </button>
            ))}
          </div>
        </div>

        {(error || notice) && <div role={error ? "alert" : "status"} className={`mx-5 mt-4 rounded-md border px-3 py-2 text-xs sm:mx-8 ${error ? "border-brick/25 bg-[#fff6f3] text-brick" : "border-emerald-700/20 bg-emerald-50 text-emerald-900"}`}>{error ?? notice}</div>}
        {loading ? <div className="p-8 text-sm text-ink/55">Loading settings…</div> : !data ? <div className="p-8 text-sm text-ink/55">Settings are unavailable.</div> : (
          <div role="tabpanel" className="w-full max-w-5xl flex-1 overflow-y-auto px-5 py-6 sm:px-8 sm:py-8">
            {tab === "general" && <GeneralPanel settings={data.general} />}
            {tab === "folders" && <FoldersPanel
              settings={data.folders} volumes={volumes} busy={busy} onChange={change} onBrowseRoot={() => void selectNativeRoots()}
              onBrowseExclusion={(rootId) => setPicker({ section: "folders", action: "exclude", rootId })}
            />}
            {tab === "code" && <CodePanel settings={data.code} busy={busy} onChange={change}
              onBrowseRoot={() => setPicker({ section: "code", action: "root" })}
              onBrowseExclusion={(rootId) => setPicker({ section: "code", action: "exclude", rootId })}
            />}
            {tab === "storage" && <StoragePanel storage={storage} />}
          </div>
        )}
      </section>
      {picker && <DirectoryPicker picker={picker} onClose={() => setPicker(null)} onSelect={selectDirectory} />}
    </main>
  );
}

function Panel({ title, detail, children }: { title: string; detail?: string; children: React.ReactNode }) {
  return <section className="mb-5 overflow-hidden rounded-lg border border-rule-grey/45 bg-white">
    <div className="border-b border-rule-grey/35 px-4 py-3 sm:px-5">
      <h2 className="text-sm font-semibold text-ink">{title}</h2>
      {detail && <p className="mt-1 text-xs leading-5 text-ink/55">{detail}</p>}
    </div>
    <div className="px-4 py-4 sm:px-5">{children}</div>
  </section>;
}

function GeneralPanel({ settings }: { settings: SettingsData["general"] }) {
  return <>
    <Panel title="Indexing" detail="Web indexing is disabled because incomplete folder enumeration can remove indexed records.">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-ink">Current behavior</p>
          <p className="mt-1 text-xs text-ink/55">No indexing or background watcher is started by the web adapter.</p>
        </div>
        <span className="rounded-full bg-sand-light px-3 py-1 text-[11px] font-medium text-ink/70">{settings.indexing_behavior}</span>
      </div>
    </Panel>
    <Panel title="DigUp desktop settings" detail="These controls depend on macOS app lifecycle or hardware APIs and do not affect this browser service.">
      <ul className="divide-y divide-rule-grey/25">
        {settings.desktop_only.map((item) => <li key={item.name} className="flex flex-wrap justify-between gap-2 py-3 first:pt-0 last:pb-0">
          <span className="text-sm text-ink">{item.name}</span>
          <span className="text-xs text-ink/50">{item.desktop_default} · Desktop only</span>
        </li>)}
      </ul>
    </Panel>
  </>;
}

function LocationList({ title, empty, items, onRemove, disabled, confirmRootRemoval = false }: {
  title: string; empty: string; items: ConfiguredFolder[]; onRemove: (id: string) => void; disabled: boolean;
  confirmRootRemoval?: boolean;
}) {
  return <div>
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink/55">{title}</h3>
    {items.length === 0 ? <p className="rounded-md bg-sand-light px-3 py-3 text-xs text-ink/55">{empty}</p> :
      <ul className="divide-y divide-rule-grey/25 rounded-md border border-rule-grey/30">
        {items.map((item) => <li key={item.id} className="flex items-center justify-between gap-3 px-3 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-ink">{item.name}</p>
            <p title={`${item.location}${item.relative_path !== "." ? ` / ${item.relative_path}` : ""}`} className="truncate text-sm text-ink/70">{item.location}{item.relative_path !== "." ? ` / ${item.relative_path}` : ""}</p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <span className={`text-xs font-medium ${item.available ? "text-emerald-800" : "text-brick"}`}>{item.available ? "Available" : "Disconnected"}</span>
            <button type="button" disabled={disabled} onClick={() => {
              if (confirmRootRemoval && !window.confirm(`Remove "${item.name}" from the configured roots? Search visibility changes immediately. Exclusions without a remaining root are also removed, and an external indexing run may remove index records. Source files are not deleted.`)) return;
              onRemove(item.id);
            }} aria-label={`Remove ${item.name}`} className="grid size-8 place-items-center rounded-md text-ink/45 hover:bg-sand-light hover:text-brick focus-visible:outline-2 focus-visible:outline-brick disabled:opacity-40">
              <X aria-hidden="true" className="size-4" />
            </button>
          </div>
        </li>)}
      </ul>}
  </div>;
}

function FoldersPanel({ settings, volumes, busy, onChange, onBrowseRoot, onBrowseExclusion }: {
  settings: FolderSettings; volumes: StorageVolume[]; busy: boolean;
  onChange: (operation: () => Promise<unknown>, message?: string) => Promise<void>;
  onBrowseRoot: () => void; onBrowseExclusion: (rootId: string) => void;
}) {
  const [extension, setExtension] = useState("");
  async function addExtension(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = extension.trim();
    if (!value) return;
    await onChange(() => settingsApi.extensions([...settings.excluded_extensions, value]));
    setExtension("");
  }
  const mounted = volumes.filter((volume) => volume.kind === "mounted");
  return <>
    <Panel title="Connected locations" detail="Mounted drives are listed for selection only. DigUp indexes folders you explicitly add below.">
      {mounted.length === 0 ? <p className="text-xs text-ink/55">No mounted volumes are listed. Use Add a folder to choose an accessible location.</p> :
        <ul className="divide-y divide-rule-grey/25">
          {mounted.map((volume) => <li key={volume.ref} className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0 last:pb-0">
            <div className="flex items-center gap-2"><HardDrive aria-hidden="true" className="size-4 text-brick" /><span className="text-sm font-medium text-ink">{volume.name}</span></div>
            <span className="text-xs text-ink/55">{volume.available ? `${bytes(volume.free_bytes)} free of ${bytes(volume.capacity_bytes)}` : "Disconnected"}</span>
          </li>)}
        </ul>}
    </Panel>
    <Panel title="Folders to index" detail="Configured roots are saved immediately. Disconnected roots remain listed and are rechecked before indexing.">
      <LocationList title="Included roots" empty="No folders selected yet." items={settings.roots} disabled={busy} confirmRootRemoval
        onRemove={(id) => void onChange(() => settingsApi.removeRoot("folders", id))} />
      <Button type="button" size="small" disabled={busy} className="mt-3" onClick={onBrowseRoot}>Add a folder</Button>
    </Panel>
    <Panel title="Excluded folders" detail="Exclusions must be inside an included root. They take effect on the next indexing run.">
      <LocationList title="Skipped folders" empty="No folder exclusions." items={settings.excluded_folders} disabled={busy}
        onRemove={(id) => void onChange(() => settingsApi.removeExclusion("folders", id))} />
      {settings.roots.map((root) => <Button key={root.id} type="button" variant="outline" size="small" disabled={busy} className="mr-2 mt-3" onClick={() => onBrowseExclusion(root.id)}>Exclude within {root.name}</Button>)}
      {settings.roots.length === 0 && <p className="mt-3 text-xs text-ink/45">Add an included root before choosing exclusions.</p>}
    </Panel>
    <Panel title="Excluded file types" detail="Add extensions one at a time. Values are case-insensitive; examples: .tmp, .log, .cache.">
      <div className="mb-3 flex flex-wrap gap-2">
        {settings.excluded_extensions.length ? settings.excluded_extensions.map((item) => <span key={item} className="inline-flex items-center gap-1 rounded-full border border-rule-grey/45 bg-sand-light px-2.5 py-1 text-xs text-ink">.{item}
          <button type="button" disabled={busy} aria-label={`Remove .${item}`} onClick={() => void onChange(() => settingsApi.extensions(settings.excluded_extensions.filter((value) => value !== item)))} className="grid size-4 place-items-center rounded-full hover:text-brick disabled:opacity-40"><X className="size-3" aria-hidden="true" /></button>
        </span>) : <p className="text-xs text-ink/50">No additional file types are excluded.</p>}
      </div>
      <form onSubmit={(event) => void addExtension(event)} className="flex flex-col gap-2 sm:flex-row">
        <label className="sr-only" htmlFor="excluded-extension">File extension</label>
        <input id="excluded-extension" value={extension} onChange={(event) => setExtension(event.target.value)} placeholder=".tmp" className="h-9 min-w-0 flex-1 rounded-md border border-rule-grey/50 bg-white px-3 text-sm outline-none focus:border-brick/70 focus:ring-2 focus:ring-brick/10" />
        <Button type="submit" variant="outline" size="small" disabled={busy || !extension.trim()}>Add extension</Button>
      </form>
    </Panel>
  </>;
}

function CodePanel({ settings, busy, onChange, onBrowseRoot, onBrowseExclusion }: {
  settings: CodeSettings; busy: boolean; onChange: (operation: () => Promise<unknown>, message?: string) => Promise<void>;
  onBrowseRoot: () => void; onBrowseExclusion: (rootId: string) => void;
}) {
  return <>
    <Panel title="Code indexing" detail="The original DigUp CLI supports separate code roots, exclusions, and a code index.">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="text-sm font-medium text-ink">Indexing {settings.indexing_available ? "available" : "unavailable"}</p><p className="mt-1 text-xs text-ink/55">{settings.index.files} code files · {settings.index.vectors} vectors · {settings.index.state}</p></div>
        <span className="rounded-full bg-sand-light px-3 py-1 text-[11px] text-ink/65">Separate code index</span>
      </div>
    </Panel>
    <Panel title="Code folders" detail="These settings configure code search. Web indexing is disabled; selecting a folder does not start indexing.">
      <LocationList title="Included code roots" empty="No code folders selected." items={settings.roots} disabled={busy} confirmRootRemoval
        onRemove={(id) => void onChange(() => settingsApi.removeRoot("code", id))} />
      <Button type="button" size="small" disabled={busy} className="mt-3" onClick={onBrowseRoot}>Add a code folder</Button>
    </Panel>
    <Panel title="Excluded code folders" detail="Code exclusions are validated against the selected code roots.">
      <LocationList title="Skipped code folders" empty="No code exclusions." items={settings.excluded_folders} disabled={busy}
        onRemove={(id) => void onChange(() => settingsApi.removeExclusion("code", id))} />
      {settings.roots.map((root) => <Button key={root.id} type="button" variant="outline" size="small" disabled={busy} className="mr-2 mt-3" onClick={() => onBrowseExclusion(root.id)}>Exclude within {root.name}</Button>)}
    </Panel>
    <Panel title="Search and editor" detail="Code search uses DigUp's separate code index. The editor preference belongs to the DigUp desktop app.">
      <p className="text-xs leading-5 text-ink/65">{settings.search_note}</p>
      <p className="mt-3 border-t border-rule-grey/25 pt-3 text-xs leading-5 text-ink/55">{settings.editor.note}</p>
    </Panel>
  </>;
}

function StoragePanel({ storage }: { storage: StorageInfo | null }) {
  if (!storage) return <Panel title="Storage status"><p className="text-xs text-ink/55">Storage information is not available from the backend.</p></Panel>;
  return <>
    <Panel title="Archive index" detail="The browser shows a safe label rather than a server filesystem path.">
      <InfoRow label="Location" value={storage.index.location} />
      <InfoRow label="Total database size" value={bytes(storage.index.size_bytes)} />
      <InfoRow label="Archive index" value={bytes(storage.index.archive_size_bytes)} />
      <InfoRow label="Code index" value={bytes(storage.index.code_size_bytes)} />
      <InfoRow label="Free space on index volume" value={bytes(storage.index.free_bytes)} />
      <InfoRow label="Files" value={storage.index.database_files.join(" · ")} />
    </Panel>
    <Panel title={storage.models.name} detail="The original EmbeddingGemma 2 Q8_0 model and media projector remain configured by the backend.">
      <InfoRow label="Location" value={storage.models.location} />
      {storage.models.files.map((file) => <InfoRow key={file.name} label={file.name} value={file.available ? `${bytes(file.size_bytes)} · available` : `Missing · expected ${bytes(file.expected_bytes)}`} />)}
      <InfoRow label="Model files" value={storage.models.all_available ? "Available" : "One or more files missing"} />
      <InfoRow label="Search encoder" value={storage.models.runtime_state === "stopped" ? "Stopped · loads when meaning search needs it" : storage.models.runtime_state} />
    </Panel>
    <p className="px-1 text-[11px] leading-5 text-ink/45">Model download, replacement, and storage relocation are not available in this browser adapter.</p>
  </>;
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return <div className="flex flex-wrap justify-between gap-2 border-b border-rule-grey/20 py-2 last:border-b-0 last:pb-0"><span className="text-xs text-ink/55">{label}</span><span className="text-right text-xs font-medium text-ink">{value}</span></div>;
}

function DirectoryPicker({ picker, onClose, onSelect }: {
  picker: { section: "folders" | "code"; action: "root" | "exclude"; rootId?: string };
  onClose: () => void; onSelect: (directoryRef: string) => void;
}) {
  const [volumes, setVolumes] = useState<StorageVolume[]>([]);
  const [volumeRef, setVolumeRef] = useState("");
  const [volumeName, setVolumeName] = useState("");
  const [browse, setBrowse] = useState<BrowseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const openVolume = useCallback(async (ref: string, name: string) => {
    setLoading(true); setError(null); setVolumeRef(ref); setVolumeName(name);
    try { setBrowse(await settingsApi.browse({ volume_ref: ref })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "This location could not be opened."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    let active = true;
    async function initialize() {
      setLoading(true);
      try {
        if (picker.rootId) {
          const directory = await settingsApi.browse({ root_id: picker.rootId, section: picker.section });
          if (active) { setBrowse(directory); setVolumeName(directory.current.name); }
        } else {
          const result = await settingsApi.volumes();
          if (!active) return;
          const available = result.volumes.filter((item) => item.available);
          setVolumes(result.volumes);
          if (available[0]) await openVolume(available[0].ref, available[0].name);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Locations could not be loaded.");
      } finally { if (active) setLoading(false); }
    }
    void initialize();
    return () => { active = false; };
  }, [openVolume, picker.rootId, picker.section]);

  async function navigate(ref: string) {
    setLoading(true); setError(null);
    try { setBrowse(await settingsApi.browse({ directory_ref: ref, section: picker.section })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "This folder could not be opened."); }
    finally { setLoading(false); }
  }

  const title = picker.action === "root" ? picker.section === "code" ? "Add a code folder" : "Add an indexing folder" : "Exclude a folder";
  return <div className="fixed inset-0 z-50 grid place-items-center bg-ink/35 p-3" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-labelledby="folder-picker-title" className="flex max-h-[min(760px,92dvh)] w-full max-w-[560px] flex-col overflow-hidden rounded-xl border border-rule-grey/60 bg-white shadow-[0_20px_60px_rgba(34,34,34,.24)]">
      <header className="flex items-start justify-between gap-3 border-b border-rule-grey/35 px-5 py-4">
        <div><h2 id="folder-picker-title" className="text-base font-semibold text-ink">{title}</h2><p className="mt-1 text-xs text-ink/55">Choose a folder on a connected location. File paths stay on this machine.</p></div>
        <button type="button" aria-label="Close folder picker" onClick={onClose} className="grid size-8 place-items-center rounded-md text-ink/55 hover:bg-sand-light hover:text-ink"><X className="size-4" aria-hidden="true" /></button>
      </header>
      {!picker.rootId && <div className="border-b border-rule-grey/30 px-5 py-3">
        <label htmlFor="storage-volume" className="mb-1 block text-[11px] font-medium text-ink/60">Connected location</label>
        <select id="storage-volume" value={volumeRef} onChange={(event) => { const item = volumes.find((volume) => volume.ref === event.target.value); if (item) void openVolume(item.ref, item.name); }} className="h-10 w-full rounded-md border border-rule-grey/45 bg-white px-3 text-sm text-ink outline-none focus:border-brick/70 focus:ring-2 focus:ring-brick/10">
          {volumes.map((volume) => <option key={volume.ref} value={volume.ref} disabled={!volume.available}>{volume.name}{volume.available ? "" : " · disconnected"}</option>)}
        </select>
      </div>}
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-rule-grey/25 bg-sand-light/70 px-5 py-3">
          <div className="min-w-0"><p className="truncate text-xs font-medium text-ink">{volumeName || "Folder"}</p><p className="truncate text-[11px] text-ink/50">{browse?.current.relative_path === "." ? "Location root" : browse?.current.relative_path}</p></div>
          {browse?.parent_ref && <Button type="button" variant="outline" size="small" disabled={loading} onClick={() => void navigate(browse.parent_ref!)}>Up one level</Button>}
        </div>
        {error && <p role="alert" className="mx-5 mt-3 rounded-md border border-brick/20 bg-[#fff6f3] px-3 py-2 text-xs text-brick">{error}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto p-2" aria-live="polite">
          {loading && <p className="px-3 py-4 text-xs text-ink/50">Loading folders…</p>}
          {!loading && browse?.entries.length === 0 && <p className="px-3 py-4 text-xs text-ink/50">No eligible subfolders here.</p>}
          {browse?.entries.map((entry) => <button key={entry.ref} type="button" onClick={() => void navigate(entry.ref)} className="flex min-h-10 w-full items-center justify-between gap-3 rounded-md px-3 text-left text-sm text-ink hover:bg-sand-light focus-visible:outline-2 focus-visible:outline-brick">
            <span className="truncate">{entry.name}</span><ChevronRight className="size-4 shrink-0 text-ink/40" aria-hidden="true" />
          </button>)}
          {browse?.truncated && <p className="px-3 py-2 text-[11px] text-ink/45">Showing the first 250 folders. Open a subfolder to continue.</p>}
        </div>
      </div>
      <footer className="flex flex-wrap justify-between gap-2 border-t border-rule-grey/35 px-5 py-4">
        <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
        <Button type="button" disabled={!browse || loading || Boolean(error)} onClick={() => browse && onSelect(browse.current.ref)}>{picker.action === "root" ? "Add this folder" : "Exclude this folder"}</Button>
      </footer>
    </section>
  </div>;
}
