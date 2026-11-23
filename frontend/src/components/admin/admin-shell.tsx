"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { adminApi, type AdminRole, type AdminUser, type AuditEvent, type RegistrationConfig } from "@/lib/admin-api";
import { SessionActions } from "@/components/auth/session-actions";
import { Button } from "@/components/ui/button";

const fieldClass = "w-full rounded border border-rule-grey/60 bg-white px-2 py-2 text-sm";
const labelClass = "grid gap-1 text-sm font-medium text-ink/80";
const allRoles: AdminRole[] = ["SUPER_ADMIN", "ADMIN", "ARCHIVE_OPERATOR", "REVIEWER", "EMPLOYEE"];
const statuses: AdminUser["status"][] = ["ACTIVE", "SUSPENDED", "DEACTIVATED", "LOCKED"];

export function AdminShell({ isSuperAdmin }: { isSuperAdmin: boolean }) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [registration, setRegistration] = useState<RegistrationConfig | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const roles = isSuperAdmin ? allRoles : allRoles.filter((role) => role === "EMPLOYEE" || role === "ARCHIVE_OPERATOR");

  const refresh = useCallback(async () => {
    const userData = await adminApi.users();
    setUsers(userData.users);
    if (isSuperAdmin) {
      const [audit, config] = await Promise.all([adminApi.audit(), adminApi.registration()]);
      setEvents(audit.events);
      setRegistration(config);
    }
  }, [isSuperAdmin]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const userData = await adminApi.users();
        if (active) setUsers(userData.users);
        if (isSuperAdmin) {
          const [audit, config] = await Promise.all([adminApi.audit(), adminApi.registration()]);
          if (active) {
            setEvents(audit.events);
            setRegistration(config);
          }
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Administration is unavailable.");
      }
    }
    void load();
    return () => { active = false; };
  }, [isSuperAdmin]);

  async function perform(action: () => Promise<unknown>, message: string): Promise<boolean> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh();
      setNotice(message);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The operation failed.");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const role = String(data.get("role"));
    if (!roles.some((item) => item === role)) {
      setError("Choose an allowed role.");
      return;
    }
    const selectedRole = roles.find((item) => item === role);
    if (!selectedRole) return;
    const success = await perform(() => adminApi.create({
      display_name: String(data.get("name")), email: String(data.get("email")), role: selectedRole,
      temporary_password: String(data.get("password")),
    }), "User created. They must change their temporary password at first sign-in.");
    if (success) form.reset();
  }

  return <main className="min-h-screen bg-sand-deep/70 p-1.5 sm:p-4">
    <section className="min-h-[calc(100dvh-12px)] w-full rounded-[13px] border border-rule-grey/70 bg-white p-5 shadow-lg sm:min-h-[calc(100dvh-32px)] sm:p-8">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-rule-grey/40 pb-4">
        <div><Link href="/archive" className="text-xs text-brick">Back to archive</Link>
          <h1 className="mt-3 text-xl font-semibold">Administration</h1>
          <p className="mt-1 text-sm text-ink/60">Manage authorised users and shared archive access.</p></div>
        <SessionActions />
      </header>
      {error ? <p role="alert" className="mt-4 text-sm text-brick">{error}</p> : null}
      {notice ? <p role="status" className="mt-4 text-sm text-emerald-700">{notice}</p> : null}
      <section className="mt-6" aria-labelledby="create-user">
        <h2 id="create-user" className="text-base font-semibold">Create a local account</h2>
        <p className="mt-1 text-xs text-ink/60">Use at least 12 characters, 8 distinct characters, and three of lowercase, uppercase, number, and symbol. Share the temporary password securely; the user must change it at first sign-in.</p>
        <form onSubmit={create} className="mt-3 grid max-w-5xl gap-3 md:grid-cols-2">
          <label className={labelClass}>Name<input className={fieldClass} name="name" minLength={2} maxLength={120} required /></label>
          <label className={labelClass}>Email<input className={fieldClass} name="email" type="email" maxLength={254} required /></label>
          <label className={labelClass}>Role<select className={fieldClass} name="role" defaultValue="EMPLOYEE">{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          <label className={labelClass}>Temporary password<input className={fieldClass} name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
          <div><Button type="submit" disabled={busy}>Create account</Button></div>
        </form>
      </section>
      <section className="mt-8 border-t border-rule-grey/40 pt-5" aria-labelledby="users-heading">
        <h2 id="users-heading" className="text-base font-semibold">Users</h2>
        <div className="mt-3 grid gap-3">{users.map((user) => <UserEditor key={user.id} user={user} roles={roles} busy={busy}
          onSave={(body) => perform(() => adminApi.update(user.id, body), "Account updated.")}
          onReset={(password) => perform(() => adminApi.resetPassword(user.id, password), "Temporary password set; existing sessions were revoked.")} />)}</div>
      </section>
      {isSuperAdmin && registration ? <section className="mt-8 border-t border-rule-grey/40 pt-5">
        <h2 className="text-base font-semibold">Demo registration</h2>
        <p className="mt-1 text-xs text-ink/60">{registration.deployment_allowed ? "Super Admin controls registration for this deployment." : "The deployment has not allowed demo registration."}</p>
        <Button className="mt-3" type="button" variant="outline" disabled={busy || (!registration.deployment_allowed && !registration.enabled)}
          onClick={() => void perform(() => adminApi.setRegistration(!registration.enabled), "Registration setting updated.")}>
          {registration.enabled ? "Disable registration" : "Enable registration"}
        </Button>
        <p className="mt-2 text-xs text-ink/60">Currently {registration.effective ? "enabled" : "disabled"}.</p>
      </section> : null}
      {isSuperAdmin ? <section className="mt-8 border-t border-rule-grey/40 pt-5">
        <h2 className="text-base font-semibold">Recent audit events</h2>
        <ul className="mt-3 grid gap-2 text-xs">{events.map((event) => <li key={event.id} className="rounded border border-rule-grey/30 p-2">
          <span className="font-medium">{event.action}</span> · {event.outcome} · {event.timestamp}
          <span className="block text-ink/55">Actor: {event.actor_user_id ?? "system"} · Target: {event.target_user_id ?? "none"}</span>
        </li>)}</ul>
      </section> : null}
    </section>
  </main>;
}

function UserEditor({ user, roles, busy, onSave, onReset }: {
  user: AdminUser;
  roles: AdminRole[];
  busy: boolean;
  onSave: (body: { display_name: string; email?: string; role: AdminRole; status: AdminUser["status"] }) => Promise<boolean>;
  onReset: (password: string) => Promise<boolean>;
}) {
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const role = roles.find((item) => item === data.get("role"));
    const status = statuses.find((item) => item === data.get("status"));
    if (!role || !status) return;
    const email = String(data.get("email"));
    await onSave({ display_name: String(data.get("name")), ...(user.identity === "local" ? { email } : {}), role, status });
  }

  async function reset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const password = String(new FormData(form).get("temporaryPassword"));
    if (await onReset(password)) form.reset();
  }

  return <div className="rounded border border-rule-grey/40 p-3">
  <form onSubmit={save} className="grid gap-2 md:grid-cols-4">
    <label className={labelClass}>Name<input className={fieldClass} name="name" defaultValue={user.display_name} minLength={2} maxLength={120} required /></label>
    <label className={labelClass}>Email ({user.identity})<input className={fieldClass} name="email" type="email" defaultValue={user.email} disabled={user.identity === "entra"} required /></label>
    <label className={labelClass}>Role<select className={fieldClass} name="role" defaultValue={user.role}>{roles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
    <label className={labelClass}>Status<select className={fieldClass} name="status" defaultValue={user.status}>{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></label>
    <div><Button type="submit" variant="outline" size="small" disabled={busy}>Save changes</Button></div>
  </form>
  {user.identity === "local" ? <form onSubmit={reset} className="mt-3 flex flex-wrap items-end gap-2 border-t border-rule-grey/30 pt-3">
    <label className={labelClass}>New temporary password<input className={fieldClass} name="temporaryPassword" type="password" autoComplete="new-password" minLength={12} maxLength={128} required /></label>
    <Button type="submit" variant="outline" size="small" disabled={busy}>Reset password</Button>
  </form> : null}
  </div>;
}
