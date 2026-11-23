export type AuthSession = {
  id: string;
  display_name: string;
  email: string;
  role: "SUPER_ADMIN" | "ADMIN" | "ARCHIVE_OPERATOR" | "REVIEWER" | "EMPLOYEE";
  status: "ACTIVE";
  password_change_required: boolean;
  csrfToken: string;
};

export class AuthApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "AuthApiError";
  }
}

export const authApi = {
  async localLogin(email: string, password: string): Promise<{ password_change_required: boolean }> {
    const response = await fetch("/auth/local/login", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) throw new AuthApiError(response.status, "Sign-in failed. Check your credentials and try again.");
    return response.json();
  },
  async registrationEnabled(): Promise<boolean> {
    const response = await fetch("/auth/local/registration", { cache: "no-store" });
    if (!response.ok) throw new AuthApiError(response.status, "Registration status is unavailable.");
    const data: { enabled: boolean } = await response.json();
    return data.enabled;
  },
  async register(displayName: string, email: string, password: string): Promise<void> {
    const response = await fetch("/auth/local/register", {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName, email, password }),
    });
    if (!response.ok) throw new AuthApiError(response.status, "Account could not be created. Check your details or contact an administrator.");
  },
  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const headers = await this.csrfHeaders();
    const response = await fetch("/auth/local/change-password", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...headers },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    if (!response.ok) throw new AuthApiError(response.status, "Password could not be changed. Check your current password.");
  },
  async session(): Promise<AuthSession> {
    const response = await fetch("/auth/session", { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new AuthApiError(response.status, "Session is no longer valid.");
    return { ...await response.json() as Omit<AuthSession, "csrfToken">,
      csrfToken: response.headers.get("x-csrf-token") ?? "" };
  },
  async logout(csrfToken: string): Promise<void> {
    const response = await fetch("/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": csrfToken },
    });
    if (!response.ok) throw new AuthApiError(response.status, "Sign out could not be completed.");
  },
  async csrfHeaders(): Promise<Record<string, string>> {
    const session = await this.session();
    if (!session.csrfToken) throw new AuthApiError(403, "The session did not provide a CSRF token.");
    return { "X-CSRF-Token": session.csrfToken };
  },
};
