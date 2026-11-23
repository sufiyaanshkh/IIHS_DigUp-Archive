"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { AuthDivider, AuthField, AuthHeading, AuthSubmit, DemoNotice, MicrosoftButton, PasswordField } from "@/components/auth/auth-primitives";
import { authApi } from "@/lib/auth-api";

const signInErrors: Record<string, string> = {
  sign_in_failed: "Microsoft sign-in could not be completed. Try again or contact IIHS IT.",
  sign_in_unavailable: "Microsoft sign-in is temporarily unavailable. Try again later.",
};

export function LoginForm({ errorCode }: { errorCode?: string }) {
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState("");
  const error = localError || (errorCode ? signInErrors[errorCode] ?? "Your IIHS account could not be verified." : "");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setLoading(true);
    setLocalError("");
    try {
      const result = await authApi.localLogin(String(data.get("email")), String(data.get("password")));
      window.location.replace(result.password_change_required ? "/change-password" : "/archive");
    } catch (reason) {
      setLocalError(reason instanceof Error ? reason.message : "Sign-in failed.");
      setLoading(false);
    }
  }

  return <div className="auth-form-content">
    <AuthHeading eyebrow="WELCOME BACK" title="Sign in to your archive" description="Use your IIHS account or local demo account." />
    <MicrosoftButton loading={loading} onClick={() => {
      setLoading(true);
      window.location.assign("/auth/microsoft/start");
    }} />
    <AuthDivider />
    <form className="auth-form" onSubmit={submit}>
      <AuthField name="email" label="Email" type="email" autoComplete="username" required />
      <PasswordField name="password" label="Password" autoComplete="current-password" required />
      <AuthSubmit loading={loading}>Sign in</AuthSubmit>
    </form>
    {error ? <DemoNotice kind="error">{error}</DemoNotice> : null}
    <p className="auth-switch"><Link href="/register" className="auth-text-link">Create a demo account</Link></p>
  </div>;
}
