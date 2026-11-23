import { redirect } from "next/navigation";
import { AuthShell } from "@/components/auth/auth-shell";
import { ChangePasswordForm } from "@/components/auth/change-password-form";
import { readServerSession } from "@/lib/server-session";

export default async function ChangePasswordPage() {
  const session = await readServerSession();
  if (!session) redirect("/");
  if (!session.password_change_required) redirect("/archive");
  return <AuthShell><ChangePasswordForm /></AuthShell>;
}
