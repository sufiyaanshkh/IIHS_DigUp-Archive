import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export type AuthenticatedUser = {
  id: string;
  display_name: string;
  email: string;
  role: "SUPER_ADMIN" | "ADMIN" | "ARCHIVE_OPERATOR" | "REVIEWER" | "EMPLOYEE";
  status: "ACTIVE";
  password_change_required: boolean;
};

const SESSION_COOKIE = "__Host-iihs_session";

export async function readServerSession(): Promise<AuthenticatedUser | null> {
  const cookie = (await cookies()).get(SESSION_COOKIE);
  if (!cookie) return null;

  const apiOrigin = process.env.ARCHIVE_API_ORIGIN ?? "http://127.0.0.1:8000";
  const response = await fetch(`${apiOrigin}/auth/session`, {
    headers: { Cookie: `${SESSION_COOKIE}=${cookie.value}` },
    cache: "no-store",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Authentication service is unavailable");
  return await response.json() as AuthenticatedUser;
}

export async function requirePageSession(roles?: AuthenticatedUser["role"][]): Promise<AuthenticatedUser> {
  const user = await readServerSession();
  if (!user) redirect("/");
  if (user.password_change_required) redirect("/change-password");
  if (roles && !roles.includes(user.role)) redirect("/archive");
  return user;
}
