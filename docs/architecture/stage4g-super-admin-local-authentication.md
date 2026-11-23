# Stage 4G implementation and verification report

## Implemented

- Local email/password authentication uses Argon2id and the existing opaque,
  server-side sessions, secure cookie, CSRF, origin checks, and authorization.
  The one-time terminal bootstrap creates a new local Super Admin; it does not
  promote an account by matching email. Initial bootstrap passwords need no
  forced change; administrator-created and reset passwords do.
- Super Admin can manage users, roles and account status, settings and indexing,
  audit events, and the demo-registration setting. Admin can manage only employees
  and archive operators. Operators can manage shared settings and indexing;
  employees cannot. Existing `REVIEWER` remains supported.
- The database prevents deletion, deactivation, or demotion of the last active
  Super Admin. Role/status/email changes, deactivation, and password resets
  revoke affected sessions. Administrative mutations check the acting session
  and role again inside the database transaction.
- Demo registration is disabled by default and creates only employees. It
  requires both deployment permission and Super Admin enablement.
- The additive auth migration preserves existing users, Entra mappings, sessions
  and audit history. It rebuilds the auth `users` table, checks foreign keys before
  commit and refuses to discard custom user indexes or triggers. It does not
  change the separate DigUp index or the original engine.
- Administrative user changes, password resets, registration configuration,
  settings changes and indexing start/stop produce audit events. The UI provides
  local sign-in, registration, forced password change and user/audit administration.

## Tested and passed

- 61 backend tests passed, including synthetic migration preservation and rollback,
  terminal bootstrap and repeat refusal, local login, registration gating, rate
  limiting, role assignment, last-Super-Admin protection, Admin privilege
  boundaries, temporary-password change/reset, deactivation/reactivation, session
  expiry/logout, anonymous API denial and mocked Entra flows.
- Frontend TypeScript check and production webpack build passed. ESLint passed with
  three existing navigation warnings. The build used an isolated project-local copy.
- The original DigUp submodule remained clean at commit
  `dc2651ad8299160bbe91e972f857e1a1599a8419`.
- After an entry-point error was reported, the bootstrap module entry point was
  corrected and tested with `--help`; the synthetic bootstrap flow was also
  retested in process. No real account was created by these tests.

## Not tested or unverified

- Fresh network-bound backend/frontend startup, actual browser login, cookie
  behavior and live protected-endpoint checks could not be verified: attempted
  loopback binds returned `EPERM`. In-process FastAPI tests are not a substitute
  for live-network verification.
- Live Microsoft Entra sign-in and the upgrade against the actual auth database
  were not tested. No real Super Admin account was created.
- The full original DigUp indexing/search integration did not pass; see below.

## Remaining issues and limitations

- The full backend run had 61 passes and one failure: the original engine integration
  reported `worker error: can't create a llama.cpp context` during indexing. The
  cause was not established. Do not treat indexing/search as live-verified.
- The previously running backend on `127.0.0.1:8003` predates the current source
  and answered protected endpoints anonymously during the audit. Do not use it
  for sensitive data. Stop it and start the updated source before verifying
  protection. Existing server processes were not changed during this work.
- Folder and indexing permissions are shared role-based permissions, not
  per-folder or per-user ACLs. Admin user management excludes `REVIEWER` accounts.
  There is no user-deletion UI/API.
- General deployment/Entra configuration remains environment-managed; the
  Super Admin UI manages demo registration, not arbitrary system settings.
  Registration has no email verification or email-based password recovery;
  the local rate limiter is not distributed abuse protection.
- A production deployment requires independent security review, HTTPS and
  operational controls; these in-process checks do not certify production readiness.

## Secure initial Super Admin bootstrap

1. Stop all backend processes using the chosen authentication database. Make
   a secure, SQLite-aware backup of the existing database before migration.
2. In your own terminal, run:

   ```sh
   cd /Users/macbookair/Desktop/iihs_Projects/digup-web/backend
   .venv/bin/python -m app.auth.bootstrap_local --db /Users/macbookair/Desktop/iihs_Projects/digup-web/var/auth.sqlite
   ```

3. Enter your display name and email at the prompts. Enter and confirm a strong
   password at the hidden prompts; do not put it in chat, arguments, source,
   environment variables, or logs. It must contain 12–128 characters, at least
   eight distinct characters, and at least three categories among lowercase,
   uppercase, numbers and symbols. The initial password is not forced to change.
4. The command applies pending auth migrations and refuses reuse after bootstrap
   or if any Super Admin already exists. If migration reports a schema conflict,
   stop and investigate rather than forcing it. Restart the backend with the same
   auth database, bound only to loopback, and configure `IIHS_PUBLIC_ORIGIN` to
   match the browser origin. Verify anonymous protected endpoints reject access
   and test sign-in in the browser before using the archive.

The existing Entra bootstrap shares the one-time marker. If it has already been
used, the local bootstrap will refuse rather than alter an existing account.
