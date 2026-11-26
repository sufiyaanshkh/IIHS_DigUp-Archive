import Image from "next/image";
import { AudioLines, FileText, Image as ImageIcon, Video } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { formatBytes, type ArchiveResult, type ImageMetadata, type MediaMetadata } from "@/lib/archive-types";
import { archiveApi, ArchiveApiError } from "@/lib/archive-api";
import { Button } from "@/components/ui/button";

type Props = {
  result: ArchiveResult;
  metadata?: MediaMetadata;
  metadataLoading: boolean;
  metadataError: string | null;
  imageMetadata?: ImageMetadata;
  imageMetadataLoading: boolean;
  imageMetadataError: string | null;
};

const photographyFields: Array<{ id: keyof ImageMetadata; label: string }> = [
  { id: "camera", label: "Camera make and model" },
  { id: "lens", label: "Lens" },
  { id: "aperture", label: "Aperture" },
  { id: "iso", label: "ISO" },
  { id: "shutter_speed", label: "Shutter speed" },
  { id: "white_balance", label: "White balance" },
  { id: "exposure_compensation", label: "Exposure compensation" },
  { id: "location", label: "Location" },
  { id: "capture_time", label: "Original capture time" },
];

function highlightedExcerpt(text: string): ReactNode[] {
  const parts: ReactNode[] = [];
  let bold = false;
  for (const piece of text.split(/([«»])/)) {
    if (piece === "«") bold = true;
    else if (piece === "»") bold = false;
    else if (piece) parts.push(bold ? <strong key={parts.length} className="font-bold text-ink">{piece}</strong> : piece);
  }
  return parts;
}

export function PreviewPane({ result, metadata, metadataLoading, metadataError, imageMetadata, imageMetadataLoading, imageMetadataError }: Props) {
  const [previewError, setPreviewError] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [playingVideo, setPlayingVideo] = useState(false);
  const [playbackError, setPlaybackError] = useState(false);
  const [expandedExcerpt, setExpandedExcerpt] = useState(false);
  const [page, setPage] = useState(() =>
    (result.segment === "page" || result.segment === "page_image") && result.loc != null && result.loc >= 1
      ? Math.floor(result.loc) : 1);
  const initialTime = Math.max(0, result.kind === "video" || result.kind === "audio" ? result.loc ?? 0 : 0);
  const [position, setPosition] = useState(initialTime);
  const [timeInput, setTimeInput] = useState(String(initialTime));
  const [timeError, setTimeError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const Icon = result.kind === "video" ? Video : result.kind === "audio" ? AudioLines : result.kind === "image" || result.kind === "screenshot" ? ImageIcon : FileText;
  const photography = result.kind === "image" || result.kind === "screenshot" || result.kind === "video";
  const pageCountValue = Number(metadata?.metadata?.pages ?? result.metadata?.pages);
  const pageCount = Number.isInteger(pageCountValue) && pageCountValue > 0 ? pageCountValue : null;
  const durationValue = Number(metadata?.metadata?.duration ?? result.metadata?.duration);
  const duration = Number.isFinite(durationValue) && durationValue > 0 ? durationValue : null;
  const previewUrl = result.engine_kind === "pdf" && result.preview_url
    ? `/api/media/${encodeURIComponent(result.id)}/preview?loc=${page}`
    : result.kind === "video" && result.preview_url
      ? `/api/media/${encodeURIComponent(result.id)}/frame?at=${position}` : result.preview_url;
  function navigateTime() {
    const time = Number(timeInput);
    const player = result.kind === "video" ? videoRef.current : audioRef.current;
    const playerDuration = player && Number.isFinite(player.duration) ? player.duration : null;
    const maximum = duration != null && playerDuration != null
      ? Math.min(duration, playerDuration) : duration ?? playerDuration;
    if (!timeInput.trim() || !Number.isFinite(time) || time < 0 || (maximum != null && time > maximum)) {
      setTimeError(maximum != null ? `Enter a time between 0 and ${maximum} seconds.` : "Enter a non-negative time in seconds.");
      return;
    }
    setTimeError(null);
    setPreviewError(false);
    setPosition(time);
    if (player && playerDuration != null) player.currentTime = time;
  }
  async function downloadOriginal() {
    setDownloadError(null);
    try {
      await archiveApi.mediaMetadata(result.id);
      window.location.assign(result.download_url);
    } catch (error) {
      setDownloadError(error instanceof ArchiveApiError && error.status === 404
        ? "This result link has expired. Search again to refresh it."
        : error instanceof Error ? error.message : "Could not retrieve this file.");
    }
  }
  return (
    <aside aria-label="Selected result preview" className="flex flex-1 flex-col border-rule-grey/45 bg-sand-light xl:border-l">
      <div className="relative mx-5 mt-5 aspect-[4/3] overflow-hidden rounded-lg border border-rule-grey/35 bg-white">
        {result.kind === "video" && playingVideo ? (
          <video ref={videoRef} controls preload="metadata" aria-label={`Play ${result.name}`} className="h-full w-full object-contain"
            src={archiveApi.mediaStreamUrl(result.id)}
            onLoadedMetadata={(event) => {
              if (Number.isFinite(event.currentTarget.duration)) {
                event.currentTarget.currentTime = Math.min(position, event.currentTarget.duration);
              }
            }}
            onError={() => setPlaybackError(true)} />
        ) : previewUrl && !previewError ? (
          <Image key={previewUrl} src={previewUrl} alt={`Preview of ${result.name}`} fill sizes="(max-width: 1279px) 100vw, 512px" unoptimized onError={() => setPreviewError(true)} className="object-contain" />
        ) : (
          <div className="grid h-full place-items-center text-brick/70"><Icon aria-hidden="true" className="size-14" strokeWidth={1.2} /></div>
        )}
        {!photography && (result.engine_kind === "pdf" || result.location) ? <span className="absolute bottom-3 left-3 rounded-full bg-ink/70 px-2.5 py-1 font-mono text-[11px] text-white">{result.engine_kind === "pdf" ? `p. ${page}` : result.location}</span> : null}
      </div>
      <div className="flex flex-1 flex-col px-5 pb-5 pt-4">
        {result.kind === "video" && !playingVideo ? <Button type="button" variant="outline" onClick={() => setPlayingVideo(true)}>Play video</Button> : null}
        {result.kind === "audio" ? <audio ref={audioRef} controls preload="metadata" aria-label={`Play ${result.name}`} className="w-full"
          src={archiveApi.mediaStreamUrl(result.id)}
          onLoadedMetadata={(event) => {
            if (Number.isFinite(event.currentTarget.duration)) {
              event.currentTarget.currentTime = Math.min(position, event.currentTarget.duration);
            }
          }}
          onError={() => setPlaybackError(true)} /> : null}
        {playbackError ? <p role="alert" className="mt-2 text-sm text-brick">Playback is unavailable in this browser. You can download the original.</p> : null}
        {result.engine_kind === "pdf" ? <div className="mt-3 flex items-center justify-between gap-2" aria-label="PDF page navigation">
          <Button type="button" variant="outline" size="small" disabled={page <= 1} onClick={() => { setPreviewError(false); setPage((value) => value - 1); }}>Previous</Button>
          <span className="text-xs text-ink/70">Page {page}{pageCount ? ` of ${pageCount}` : ""}</span>
          <Button type="button" variant="outline" size="small" disabled={pageCount != null && page >= pageCount} onClick={() => { setPreviewError(false); setPage((value) => value + 1); }}>Next</Button>
        </div> : null}
        {result.kind === "video" || result.kind === "audio" ? <div className="mt-3">
          <div className="flex items-end gap-2">
            <label className="min-w-0 flex-1 text-xs text-ink/70">Time (seconds)
              <input type="number" min="0" max={duration ?? undefined} step="any" value={timeInput}
                onChange={(event) => { setTimeInput(event.target.value); setTimeError(null); }}
                className="mt-1 h-9 w-full rounded-md border border-rule-grey/50 bg-white px-2 text-sm text-ink" />
            </label>
            <Button type="button" variant="outline" size="small" onClick={navigateTime}>Go</Button>
          </div>
          {timeError ? <p role="alert" className="mt-1 text-xs text-brick">{timeError}</p> : null}
        </div> : null}
        {!photography ? <h2 className="break-words text-lg font-semibold leading-6 text-ink">{result.name}</h2> : null}
        {!photography ? <p className="mt-1 break-all text-sm text-ink/70">{result.folder}</p> : null}
        {!photography ? <p className="mt-1 truncate text-sm text-ink/70">{metadataLoading ? "Loading metadata…" : result.details}</p> : null}
        {!photography && metadata?.metadata && Object.entries(metadata.metadata).length ? <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-2 text-sm text-ink/70">{Object.entries(metadata.metadata).slice(0, 4).map(([key, value]) => <div key={key} className="min-w-0"><dt className="capitalize">{key.replaceAll("_", " ")}</dt><dd className="truncate font-medium text-ink">{value}</dd></div>)}</dl> : null}
        {photography ? <section aria-label="File information" className="mt-4 border-t border-rule-grey/35 pt-4">
          <h3 className="text-sm font-semibold text-ink">File information</h3>
          <dl className="mt-3 space-y-3">
            {[
              ["Filename", result.name || "Not available"],
              ["Type", result.kind || "Not available"],
              ["Size", metadataLoading ? "Loading…" : metadata?.current_size != null ? formatBytes(metadata.current_size) : "Not available"],
              ["Dimensions", imageMetadataLoading ? "Loading…" : imageMetadata?.dimensions || "Not available"],
              ["Source-relative location", metadataLoading ? "Loading…" : metadata?.source_relative_path || "Not available"],
            ].map(([label, value]) => <div key={label} className="grid grid-cols-2 gap-3 text-sm leading-5">
              <dt className="text-ink/70">{label}</dt>
              <dd className="break-all text-right font-medium text-ink">{value}</dd>
            </div>)}
          </dl>
        </section> : null}
        {photography ? <section aria-label="Photography metadata" className="mt-4 border-t border-rule-grey/35 pt-4">
          <h3 className="text-sm font-semibold text-ink">Photography details</h3>
          {imageMetadataLoading ? <p role="status" className="mt-2 text-sm text-ink/70">Reading embedded metadata…</p> : null}
          {imageMetadataError ? <p role="alert" className="mt-2 text-sm text-brick">{imageMetadataError}</p> : null}
          {!imageMetadataLoading ? <dl className="mt-3 space-y-3">
            {photographyFields.map((field) => <div key={field.id} className="grid grid-cols-2 gap-3 text-sm leading-5">
              <dt className="text-ink/70">{field.label}</dt>
              <dd className="break-words text-right font-medium text-ink">{imageMetadata?.[field.id] || "Not available"}</dd>
            </div>)}
          </dl> : null}
        </section> : null}
        <div className="mt-4 flex items-start gap-2.5 border-t border-rule-grey/35 pt-3">
          <span className="mt-0.5 size-2 shrink-0 rounded-full bg-brick" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-ink">{result.reason}</p>
            {result.excerpt ? <>
              <p className={`mt-1 whitespace-pre-wrap text-sm leading-5 text-ink/70 ${expandedExcerpt ? "" : "line-clamp-3"}`}>{highlightedExcerpt(result.excerpt)}</p>
              <button type="button" aria-expanded={expandedExcerpt}
                onClick={() => setExpandedExcerpt((expanded) => !expanded)}
                className="mt-1 text-xs font-medium text-brick focus-visible:outline-2 focus-visible:outline-brick">
                {expandedExcerpt ? "Show less" : "Show full excerpt"}
              </button>
            </> : null}
          </div>
        </div>
        <div className="mt-4 flex gap-2">
          <Button type="button" onClick={downloadOriginal}>Download original</Button>
        </div>
        {downloadError || metadataError ? <p role="alert" className="mt-2 text-sm text-brick">{downloadError ?? metadataError}</p> : previewError ? <p role="alert" className="mt-2 text-sm text-brick">Preview unavailable for this page or media.</p> : !photography ? <p className="mt-2 text-xs text-ink/70">{result.location ? `Source location: ${result.location}` : "Preview and metadata from DigUp."}</p> : null}
      </div>
    </aside>
  );
}
