import { ArchiveShell } from "@/components/archive/archive-shell";
import { requirePageSession } from "@/lib/server-session";

export default async function ArchivePage() {
  const user = await requirePageSession();
  return <ArchiveShell user={user} />;
}
