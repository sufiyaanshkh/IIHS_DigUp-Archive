import { z } from "zod";

const email = z.string().trim().email("Enter a valid email address.");
const password = z.string().min(12, "Use at least 12 characters.").max(128, "Use at most 128 characters.")
  .refine((value) => [/[a-z]/.test(value), /[A-Z]/.test(value), /[0-9]/.test(value), /[^a-zA-Z0-9]/.test(value)].filter(Boolean).length >= 3 && new Set(value).size >= 8,
    "Use 8 distinct characters and at least three of lowercase, uppercase, number, and symbol.");

export const loginSchema = z.object({ email, password: z.string().min(1, "Enter your password.") });
export const registerSchema = z.object({
  fullName: z.string().trim().min(2, "Enter your full name."),
  // The organisation's accepted email domains have not yet been configured.
  email,
  password,
  confirmPassword: z.string().min(1, "Confirm your password."),
  terms: z.boolean().refine(Boolean, "Please acknowledge the terms and privacy notice."),
}).refine((value) => value.password === value.confirmPassword, { path: ["confirmPassword"], message: "Passwords do not match." });
export const emailSchema = z.object({ email });
export const resetPasswordSchema = z.object({ password, confirmPassword: z.string().min(1, "Confirm your password.") }).refine((value) => value.password === value.confirmPassword, { path: ["confirmPassword"], message: "Passwords do not match." });

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
export type EmailValues = z.infer<typeof emailSchema>;
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;

export function passwordStrength(value: string) {
  if (!value) return 0;
  let score = 0;
  if (value.length >= 12) score++;
  if (/[A-Za-z]/.test(value) && /[0-9]/.test(value)) score++;
  if (value.length >= 12) score++;
  if (/[^A-Za-z0-9]/.test(value)) score++;
  return score;
}
