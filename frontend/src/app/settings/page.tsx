import { SettingsShell } from "@/components/settings/settings-shell";
import { requirePageSession } from "@/lib/server-session";

export default async function SettingsPage() {
  await requirePageSession(["SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR"]);
  return <SettingsShell />;
}
