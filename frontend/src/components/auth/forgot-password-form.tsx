"use client";

import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { ArrowLeft, MailCheck } from "lucide-react";
import { AuthField, AuthHeading, AuthSubmit, DemoNotice } from "@/components/auth/auth-primitives";
import { emailSchema, type EmailValues } from "@/lib/auth-schemas";

export function ForgotPasswordForm() {
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const { register, handleSubmit, formState: { errors } } = useForm<EmailValues>({ resolver: zodResolver(emailSchema), mode: "onBlur" });
  const submit = async () => { setLoading(true); await new Promise((resolve) => window.setTimeout(resolve, 650)); setLoading(false); setSubmitted(true); };
  return <div className="auth-form-content">
    <Link href="/" className="auth-back"><ArrowLeft size={16} /> Back to sign in</Link>
    {submitted ? <div className="auth-confirmation"><span className="auth-confirm-icon"><MailCheck size={23} /></span><AuthHeading eyebrow="REQUEST PREVIEW" title="Check your inbox" description="If this were connected, password reset instructions would be sent to the address you entered." /><DemoNotice>Demo only: no email was sent. Password recovery is not connected.</DemoNotice><Link href="/reset-password" className="auth-submit">Preview reset form</Link><button type="button" className="auth-secondary-action" onClick={() => setSubmitted(false)}>Try another address</button></div> : <>
      <AuthHeading eyebrow="ACCOUNT RECOVERY" title="Reset your password" description="Enter your organisation email and we’ll prepare the next step." />
      <form className="auth-form" noValidate onSubmit={handleSubmit(submit)}><AuthField label="Email address" type="email" autoComplete="email" placeholder="name@organisation.org" {...register("email")} error={errors.email?.message} /><AuthSubmit loading={loading}>Send reset instructions</AuthSubmit></form>
    </>}
  </div>;
}
