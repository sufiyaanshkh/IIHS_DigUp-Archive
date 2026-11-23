type Props = { resultCount: number; query: string; engineReady: boolean; backendUnavailable: boolean; indexedFiles: number; searchError: string | null };

export function StatusBar({ resultCount, query, engineReady, backendUnavailable, indexedFiles, searchError }: Props) {
  return (
    <footer className="flex min-h-10 shrink-0 items-center justify-between gap-3 border-t border-rule-grey/45 bg-white px-4 text-xs text-ink/75 sm:px-5">
      <span className="min-w-0 truncate" role={searchError || backendUnavailable ? "status" : undefined}>{searchError ?? (backendUnavailable ? "DigUp backend unavailable" : query ? `${indexedFiles} files indexed${engineReady ? " · DigUp connected" : " · connecting to DigUp…"}` : engineReady ? "DigUp connected · Enter a description to search" : "Connecting to DigUp…")}</span>
      <span className="shrink-0 font-mono tabular-nums">{resultCount} {resultCount === 1 ? "result" : "results"}</span>
    </footer>
  );
}
