"use client";

import { useState, type FormEvent } from "react";
import { AuthHeading, AuthSubmit, DemoNotice, PasswordField } from "@/components/auth/auth-primitives";
import { authApi } from "@/lib/auth-api";

export function ChangePasswordForm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const password = String(data.get("newPassword"));
    if (password !== data.get("confirmPassword")) {
      setError("New passwords do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await authApi.changePassword(String(data.get("currentPassword")), password);
      window.location.replace("/archive");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Password could not be changed.");
      setBusy(false);
    }
  }

  return <div className="auth-form-content">
    <AuthHeading eyebrow="ACCOUNT SECURITY" title="Change your temporary password" description="Use at least 12 characters, 8 distinct characters, and three of lowercase, uppercase, number, and symbol." />
    <form className="auth-form" onSubmit={submit}>
      <PasswordField name="currentPassword" label="Temporary password" autoComplete="current-password" required />
      <PasswordField name="newPassword" label="New password" autoComplete="new-password" minLength={12} maxLength={128} required />
      <PasswordField name="confirmPassword" label="Confirm new password" autoComplete="new-password" minLength={12} maxLength={128} required />
      {error ? <DemoNotice kind="error">{error}</DemoNotice> : null}
      <AuthSubmit loading={busy}>Change password</AuthSubmit>
    </form>
  </div>;
}
