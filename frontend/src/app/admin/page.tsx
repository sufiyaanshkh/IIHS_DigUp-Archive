import { AdminShell } from "@/components/admin/admin-shell";
import { requirePageSession } from "@/lib/server-session";

export default async function AdminPage() {
  const user = await requirePageSession(["SUPER_ADMIN", "ADMIN"]);
  return <AdminShell isSuperAdmin={user.role === "SUPER_ADMIN"} />;
}
