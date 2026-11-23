"use client";

import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { AuthHeading, AuthSubmit, DemoNotice, PasswordField } from "@/components/auth/auth-primitives";
import { passwordStrength, resetPasswordSchema, type ResetPasswordValues } from "@/lib/auth-schemas";

export function ResetPasswordForm() {
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const { register, control, handleSubmit, formState: { errors } } = useForm<ResetPasswordValues>({ resolver: zodResolver(resetPasswordSchema), mode: "onBlur" });
  const value = useWatch({ control, name: "password", defaultValue: "" }) ?? "";
  const strength = passwordStrength(value);
  const submit = async () => { setLoading(true); await new Promise((resolve) => window.setTimeout(resolve, 650)); setLoading(false); setNotice("Preview only: password reset is not connected. No password was changed."); };
  return <div className="auth-form-content">
    <AuthHeading eyebrow="NEW PASSWORD" title="Choose a new password" description="Set a strong password for your archive account." />
    <form className="auth-form" noValidate onSubmit={handleSubmit(submit)}>
      <PasswordField label="New password" autoComplete="new-password" placeholder="At least 8 characters" {...register("password")} error={errors.password?.message} />
      <div className="auth-strength"><div className="auth-strength-track" aria-label={`Password strength ${strength} of 4`}>{[1, 2, 3, 4].map((step) => <span key={step} className={strength >= step ? `strength-${strength}` : ""} />)}</div><span>{value ? ["Too short", "Fair", "Good", "Strong", "Very strong"][strength] : "Use 8+ characters with a number"}</span></div>
      <PasswordField label="Confirm new password" autoComplete="new-password" placeholder="Re-enter your password" {...register("confirmPassword")} error={errors.confirmPassword?.message} />
      {notice ? <DemoNotice>{notice}</DemoNotice> : null}
      <AuthSubmit loading={loading}>Update password</AuthSubmit>
    </form>
    <p className="auth-switch"><Link href="/" className="auth-text-link">Return to sign in</Link></p>
  </div>;
}
