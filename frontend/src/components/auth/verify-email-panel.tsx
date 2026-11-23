"use client";

import Link from "next/link";
import { useState } from "react";
import { MailCheck, MailSearch } from "lucide-react";
import { DemoNotice } from "@/components/auth/auth-primitives";

export function VerifyEmailPanel() {
  const [resent, setResent] = useState(false);
  const [confirmedPreview, setConfirmedPreview] = useState(false);
  return <div className="auth-form-content auth-verify-content">
    <span className="auth-confirm-icon">{confirmedPreview ? <MailCheck size={24} /> : <MailSearch size={24} />}</span>
    <p className="auth-kicker">{confirmedPreview ? "PREVIEW STATE" : "EMAIL VERIFICATION"}</p>
    <h2>{confirmedPreview ? "Verification complete" : "Check your email"}</h2>
    <p className="auth-description">{confirmedPreview ? "This view previews the completed verification state." : "Verify your organisation email to continue. A verification email is not sent in this frontend preview."}</p>
    {confirmedPreview ? <DemoNotice>Simulation only: no email address has been verified.</DemoNotice> : <>
      {resent ? <DemoNotice>Resend preview complete. No email was sent.</DemoNotice> : <DemoNotice>Verification is simulated. No message has been sent.</DemoNotice>}
      <button type="button" className="auth-submit" onClick={() => { setResent(false); setConfirmedPreview(true); }}>Preview verified state</button>
      <button type="button" className="auth-secondary-action" onClick={() => setResent(true)}>Resend verification email</button>
    </>}
    <p className="auth-switch"><Link href="/" className="auth-text-link">Return to sign in</Link></p>
  </div>;
}
