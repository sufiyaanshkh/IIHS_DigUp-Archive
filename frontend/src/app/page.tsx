import { LoginForm } from "@/components/auth/login-form";
import { AuthShell } from "@/components/auth/auth-shell";
import { redirect } from "next/navigation";
import { readServerSession } from "@/lib/server-session";

export default async function Home({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const session = await readServerSession();
  if (session) redirect(session.password_change_required ? "/change-password" : "/archive");
  const { error } = await searchParams;
  return (
    <AuthShell>
      <LoginForm errorCode={error} />
    </AuthShell>
  );
}
