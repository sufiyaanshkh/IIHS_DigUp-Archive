import { AllArchiveShell } from "@/components/archive/all-archive-shell";
import { requirePageSession } from "@/lib/server-session";

export default async function AllArchivePage({ searchParams }: {
  searchParams: Promise<{ source?: string; folder?: string }>;
}) {
  const user = await requirePageSession();
  const params = await searchParams;
  const sourceId = params.source && params.source.length <= 64 ? params.source : null;
  const folder = params.folder && params.folder.length <= 1024 ? params.folder : ".";
  return <AllArchiveShell user={user} initialSourceId={sourceId} initialFolder={folder} />;
}
