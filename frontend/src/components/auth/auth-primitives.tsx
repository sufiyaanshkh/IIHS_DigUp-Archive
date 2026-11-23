"use client";

import type { InputHTMLAttributes, ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useState } from "react";

export function AuthHeading({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <header className="auth-heading"><p className="auth-kicker">{eyebrow}</p><h2>{title}</h2><p>{description}</p></header>;
}

export function AuthField({ label, error, className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const id = props.id ?? props.name;
  return (
    <div className={`auth-field ${className}`}>
      <label htmlFor={id}>{label}</label>
      <input {...props} id={id} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : props["aria-describedby"]} />
      {error ? <span id={`${id}-error`} className="auth-field-error" role="alert">{error}</span> : null}
    </div>
  );
}

export function PasswordField({ label, error, className = "", ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string }) {
  const [visible, setVisible] = useState(false);
  const id = props.id ?? props.name;
  return (
    <div className={`auth-field ${className}`}>
      <label htmlFor={id}>{label}</label>
      <div className={`auth-password-wrap ${error ? "has-error" : ""}`}>
        <input {...props} id={id} type={visible ? "text" : "password"} aria-invalid={Boolean(error)} aria-describedby={error ? `${id}-error` : props["aria-describedby"]} />
        <button type="button" className="auth-visibility" onClick={() => setVisible((shown) => !shown)} aria-label={visible ? "Hide password" : "Show password"} aria-pressed={visible}>
          {visible ? <EyeOff size={17} aria-hidden="true" /> : <Eye size={17} aria-hidden="true" />}
        </button>
      </div>
      {error ? <span id={`${id}-error`} className="auth-field-error" role="alert">{error}</span> : null}
    </div>
  );
}

export function AuthSubmit({ children, loading = false }: { children: ReactNode; loading?: boolean }) {
  return <button className="auth-submit" type="submit" disabled={loading}>{loading ? <><span className="auth-spinner" aria-hidden="true" />Please wait…</> : children}</button>;
}

export function DemoNotice({ kind = "info", children }: { kind?: "info" | "success" | "error"; children: ReactNode }) {
  return <p className={`auth-notice auth-notice-${kind}`} role={kind === "error" ? "alert" : "status"}>{children}</p>;
}

export function MicrosoftButton({ onClick, loading = false }: { onClick: () => void; loading?: boolean }) {
  return (
    <button type="button" className="auth-microsoft" onClick={onClick} disabled={loading}>
      <span className="microsoft-mark" aria-hidden="true"><i /><i /><i /><i /></span>
      {loading ? "Redirecting to Microsoft…" : "Continue with Microsoft"}
    </button>
  );
}

export function AuthDivider() { return <div className="auth-divider"><span>or use your email</span></div>; }
