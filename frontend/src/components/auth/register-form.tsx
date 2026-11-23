"use client";

import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { AuthField, AuthHeading, AuthSubmit, DemoNotice, PasswordField } from "@/components/auth/auth-primitives";
import { passwordStrength, registerSchema, type RegisterValues } from "@/lib/auth-schemas";
import { authApi } from "@/lib/auth-api";

export function RegisterForm() {
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const { register, control, handleSubmit, formState: { errors } } = useForm<RegisterValues>({ resolver: zodResolver(registerSchema), mode: "onBlur", defaultValues: { terms: false } });
  const passwordValue = useWatch({ control, name: "password", defaultValue: "" });
  const strength = passwordStrength(passwordValue ?? "");
  useEffect(() => {
    authApi.registrationEnabled().then(setEnabled).catch(() => setNotice("Registration status is unavailable."));
  }, []);
  const submit = async (values: RegisterValues) => {
    setLoading(true);
    setNotice("");
    try {
      await authApi.register(values.fullName, values.email, values.password);
      setNotice("Account created. You can now sign in.");
    } catch (reason) {
      setNotice(reason instanceof Error ? reason.message : "Account could not be created.");
    } finally {
      setLoading(false);
    }
  };
  return <div className="auth-form-content auth-form-content-compact">
    <AuthHeading eyebrow="REQUEST ACCESS" title="Create your archive account" description="Use your organisational email to request access to IIHS materials." />
    {enabled ? <form className="auth-form" noValidate onSubmit={handleSubmit(submit)}>
      <AuthField label="Full name" autoComplete="name" placeholder="Your name" {...register("fullName")} error={errors.fullName?.message} />
      <AuthField label="Organisation email" type="email" autoComplete="email" placeholder="name@organisation.org" {...register("email")} error={errors.email?.message} />
      <PasswordField label="Password" autoComplete="new-password" placeholder="At least 12 characters" {...register("password")} error={errors.password?.message} />
      <div className="auth-strength" aria-live="polite"><div className="auth-strength-track" aria-label={`Password strength ${strength} of 4`}>{[1, 2, 3, 4].map((step) => <span key={step} className={strength >= step ? `strength-${strength}` : ""} />)}</div><span>{passwordValue ? ["Too short", "Fair", "Good", "Strong", "Very strong"][strength] : "Use at least 12 characters"}</span></div>
      <PasswordField label="Confirm password" autoComplete="new-password" placeholder="Re-enter your password" {...register("confirmPassword")} error={errors.confirmPassword?.message} />
      <div className="auth-check-row"><label className="auth-check"><input type="checkbox" {...register("terms")} /><span>I acknowledge the terms of use and privacy notice.</span></label>{errors.terms ? <span className="auth-field-error" role="alert">{errors.terms.message}</span> : null}</div>
      <AuthSubmit loading={loading}>Create account</AuthSubmit>
    </form> : enabled === false ? <DemoNotice>Demo registration is not enabled. Contact an administrator.</DemoNotice> : null}
    {notice ? <DemoNotice>{notice}</DemoNotice> : null}
    <p className="auth-switch">Already have an account? <Link href="/" className="auth-text-link">Sign in</Link></p>
  </div>;
}
