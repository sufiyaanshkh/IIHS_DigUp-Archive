import Image from "next/image";
import { AudioLines, FileText, Image as ImageIcon, Video } from "lucide-react";
import { useState } from "react";
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

export function PreviewPane({ result, metadata, metadataLoading, metadataError, imageMetadata, imageMetadataLoading, imageMetadataError }: Props) {
  const [previewError, setPreviewError] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [playingVideo, setPlayingVideo] = useState(false);
  const [playbackError, setPlaybackError] = useState(false);
  const [expandedExcerpt, setExpandedExcerpt] = useState(false);
  const Icon = result.kind === "video" ? Video : result.kind === "audio" ? AudioLines : result.kind === "image" || result.kind === "screenshot" ? ImageIcon : FileText;
  const photography = result.kind === "image" || result.kind === "screenshot" || result.kind === "video";
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
          <video controls preload="metadata" aria-label={`Play ${result.name}`} className="h-full w-full object-contain"
            src={archiveApi.mediaStreamUrl(result.id)}
            onLoadedMetadata={(event) => {
              if (result.loc != null && Number.isFinite(event.currentTarget.duration)) {
                event.currentTarget.currentTime = Math.max(0, Math.min(result.loc, event.currentTarget.duration));
              }
            }}
            onError={() => setPlaybackError(true)} />
        ) : result.preview_url && !previewError ? (
          <Image key={result.preview_url} src={result.preview_url} alt={`Preview of ${result.name}`} fill sizes="(max-width: 1279px) 100vw, 512px" unoptimized onError={() => setPreviewError(true)} className="object-contain" />
        ) : (
          <div className="grid h-full place-items-center text-brick/70"><Icon aria-hidden="true" className="size-14" strokeWidth={1.2} /></div>
        )}
        {!photography && result.location ? <span className="absolute bottom-3 left-3 rounded-full bg-ink/70 px-2.5 py-1 font-mono text-[11px] text-white">{result.location}</span> : null}
      </div>
      <div className="flex flex-1 flex-col px-5 pb-5 pt-4">
        {result.kind === "video" && !playingVideo ? <Button type="button" variant="outline" onClick={() => setPlayingVideo(true)}>Play video</Button> : null}
        {result.kind === "audio" ? <audio controls preload="metadata" aria-label={`Play ${result.name}`} className="w-full"
          src={archiveApi.mediaStreamUrl(result.id)}
          onLoadedMetadata={(event) => {
            if (result.loc != null && Number.isFinite(event.currentTarget.duration)) {
              event.currentTarget.currentTime = Math.max(0, Math.min(result.loc, event.currentTarget.duration));
            }
          }}
          onError={() => setPlaybackError(true)} /> : null}
        {playbackError ? <p role="alert" className="mt-2 text-sm text-brick">Playback is unavailable in this browser. You can download the original.</p> : null}
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
        {!photography ? <div className="mt-4 flex items-start gap-2.5 border-t border-rule-grey/35 pt-3">
          <span className="mt-0.5 size-2 shrink-0 rounded-full bg-brick" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-ink">{result.reason}</p>
            {result.excerpt ? <>
              <p className={`mt-1 whitespace-pre-wrap text-sm leading-5 text-ink/70 ${expandedExcerpt ? "" : "line-clamp-3"}`}>{result.excerpt}</p>
              <button type="button" aria-expanded={expandedExcerpt}
                onClick={() => setExpandedExcerpt((expanded) => !expanded)}
                className="mt-1 text-xs font-medium text-brick focus-visible:outline-2 focus-visible:outline-brick">
                {expandedExcerpt ? "Show less" : "Show full excerpt"}
              </button>
            </> : null}
          </div>
        </div> : null}
        <div className="mt-4 flex gap-2">
          <Button type="button" onClick={downloadOriginal}>Download original</Button>
        </div>
        {downloadError || metadataError ? <p role="alert" className="mt-2 text-sm text-brick">{downloadError ?? metadataError}</p> : previewError ? <p role="alert" className="mt-2 text-sm text-brick">Preview unavailable. Search again to refresh this result.</p> : !photography ? <p className="mt-2 text-xs text-ink/70">{result.location ? `Source location: ${result.location}` : "Preview and metadata from DigUp."}</p> : null}
      </div>
    </aside>
  );
}
