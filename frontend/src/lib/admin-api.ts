import { authApi } from "@/lib/auth-api";

export type AdminRole = "SUPER_ADMIN" | "ADMIN" | "ARCHIVE_OPERATOR" | "REVIEWER" | "EMPLOYEE";
export type AdminUser = {
  id: string;
  display_name: string;
  email: string;
  role: AdminRole;
  status: "ACTIVE" | "DEACTIVATED" | "SUSPENDED" | "LOCKED";
  identity: "entra" | "local";
};
export type AuditEvent = {
  id: string;
  timestamp: string;
  action: string;
  outcome: string;
  actor_user_id: string | null;
  target_user_id: string | null;
};
export type RegistrationConfig = { enabled: boolean; deployment_allowed: boolean; effective: boolean };

async function request<T>(path: string, method = "GET", body?: object): Promise<T> {
  const csrf = method === "GET" ? {} : await authApi.csrfHeaders();
  const response = await fetch(path, {
    method, credentials: "same-origin", cache: "no-store",
    headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}), ...csrf },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const data: { detail?: unknown } = await response.json();
    throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${response.status})`);
  }
  return response.json();
}

export const adminApi = {
  users: () => request<{ users: AdminUser[] }>("/api/admin/users"),
  create: (body: { email: string; display_name: string; role: AdminRole; temporary_password: string }) =>
    request<{ id: string }>("/api/admin/users", "POST", body),
  update: (id: string, body: { display_name: string; email?: string; role: AdminRole; status: AdminUser["status"] }) =>
    request<{ id: string }>(`/api/admin/users/${encodeURIComponent(id)}`, "PATCH", body),
  resetPassword: (id: string, temporaryPassword: string) =>
    request<{ message: string }>(`/api/admin/users/${encodeURIComponent(id)}/temporary-password`, "POST", { temporary_password: temporaryPassword }),
  audit: () => request<{ events: AuditEvent[] }>("/api/admin/audit"),
  registration: () => request<RegistrationConfig>("/api/admin/registration"),
  setRegistration: (enabled: boolean) => request<{ enabled: boolean }>("/api/admin/registration", "PUT", { enabled }),
};
