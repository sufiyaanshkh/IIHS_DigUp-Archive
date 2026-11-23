# Authentication foundation

This service supports Microsoft Entra and local email/password sign-in using the same
opaque server-side sessions. Authentication data remains in `var/auth.sqlite`, separate
from any archive index. Versioned migrations preserve Entra identities and add local
credentials and administration settings.

## Install and run

From `digup-web/backend/`:

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m app.auth.database migrate
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The API should be behind the same-origin HTTPS reverse proxy as the frontend. Route
`/auth/*` to this service; do not expose the SQLite file or bind the service to a public
interface without a reviewed deployment design. The app redacts callback query strings
from Uvicorn access logs; configure the reverse proxy and any telemetry to omit query
strings on `/auth/microsoft/callback` too, since Entra returns the authorization code there.

## Configuration

Set these in the process environment or deployment secret manager:

| Variable | Purpose |
| --- | --- |
| `IIHS_ENTRA_TENANT_ID` | The IIHS Entra tenant UUID; the OIDC authority and token tenant are pinned to it. |
| `IIHS_ENTRA_CLIENT_ID` | App registration client ID. |
| `IIHS_ENTRA_CLIENT_SECRET` | Server-side client secret. Never put it in frontend code or commit it. |
| `IIHS_ENTRA_REDIRECT_URI` | Exact registered callback URI, ending in `/auth/microsoft/callback`. |
| `IIHS_AUTH_DB_PATH` | Optional persistent path for the separate auth SQLite database. Defaults to `../var/auth.sqlite` from project root. |
| `IIHS_SESSION_MAX_AGE_SECONDS` | Optional lifetime from 1 through 43,200 seconds; defaults to 43,200 (12 hours). |
| `IIHS_PUBLIC_ORIGIN` | Optional canonical HTTPS origin used for login redirects and logout Origin checks. |
| `IIHS_DEMO_REGISTRATION_ALLOWED` | Set to `1` to permit a Super Admin to enable local demo registration. Default is off. |

Configure the Entra app registration for single-tenant OpenID Connect authorization-code
flow. Register the exact redirect URI. The ID token must include Entra's optional `acct`
claim (`0` for a member, `1` for a guest); missing values are rejected. `tid` and `oid`
are used as the account identity. Email is profile data only; no email-domain test is used.

Authlib handles discovery, state binding, PKCE, code exchange, signature verification,
issuer/audience/time checks and nonce validation. Its state, nonce and PKCE verifier are
kept in SQLite behind short-lived, HttpOnly, SameSite=Lax cookies named per OAuth state,
so separate login tabs do not overwrite one another. The callback then checks tenant and
member eligibility before provisioning an `ACTIVE` / `EMPLOYEE` account. Existing role
and status are not changed by sign-in.

## Endpoints

- `GET /auth/microsoft/start` begins Entra OIDC.
- `GET /auth/microsoft/callback` validates the flow and creates a server-side session.
- `GET /auth/session` returns only `id`, `display_name`, `email`, `role` and `status`; an
  `X-CSRF-Token` response header is supplied for the session's state-changing requests.
- `POST /auth/logout` checks same-origin `Origin` and CSRF token, revokes the session and
  clears the cookie.
- `/auth/local/login`, `/auth/local/register`, and `/auth/local/change-password` implement
  local sign-in and password management. Registration requires both the deployment flag
  and the Super Admin setting; it creates only `EMPLOYEE` accounts.
- `/api/admin/*` provides role-protected account administration; audit-log and
  registration-configuration access require `SUPER_ADMIN`. Mutations require origin
  and CSRF checks. Administrators may manage only employees and archive operators.

The login cookie is `__Host-iihs_session`, HttpOnly, Secure, SameSite=Lax,
Path=/, and bounded by the configured maximum lifetime. Its random secret is never stored
in SQLite; only SHA-256 of that secret is persisted. Entra tokens are used only during the
server callback and are not returned or persisted.

## Initial Super Administrator

An authorised IIHS operator obtains the employee's Object ID from the IIHS Entra admin
center: **Identity > Users > All users**, open the employee record, confirm **User type** is
Member and the account is enabled, then copy **Object ID**. Verify the tenant UUID with IIHS
IT. Do not accept an email address as identity evidence. The command independently queries
Microsoft Graph for that Object ID and refuses guests or disabled accounts.

The app registration needs Microsoft Graph **Application** permission `User.Read.All`
with administrator consent for this one-time lookup. Set up the secret in the operator's
secret manager/environment, then run from `backend/`:

```sh
.venv/bin/python -m app.auth.bootstrap_admin \
  --tenant-id "$IIHS_ENTRA_TENANT_ID" \
  --object-id "<verified Entra Object ID>"
```

The CLI prints the Graph-resolved name and email and requires typing `BOOTSTRAP`. It runs
only as a command-line process, uses `BEGIN IMMEDIATE`, refuses if any Super Administrator
already exists, promotes an existing ACTIVE Employee when appropriate, and records an audit
event. There is no HTTP bootstrap or administrator self-registration route.

## Initial local Super Administrator

The local bootstrap and the existing Entra bootstrap share a permanent one-time marker.
Neither bootstrap is available through public registration, and a local account is never
promoted or linked to an Entra identity merely because the email matches. Bootstrap
refuses if an earlier bootstrap or Super Admin already exists. The last active Super Admin
cannot be demoted, deactivated, or deleted.

Stop backend processes using the chosen database and make a secure SQLite-aware backup
before upgrading an existing database. To use the project's default auth database:

```sh
cd /Users/macbookair/Desktop/iihs_Projects/digup-web/backend
.venv/bin/python -m app.auth.bootstrap_local --db /Users/macbookair/Desktop/iihs_Projects/digup-web/var/auth.sqlite
```

Enter the display name and email at the prompts, then enter and confirm the password
using the hidden terminal prompts. Never put the password in arguments, environment
variables, source files, or chat. The password needs 12–128 characters, at least eight
distinct characters, and at least three of lowercase, uppercase, number, and symbol.
The initial bootstrap password does not require a change. Administrator-created or
reset temporary passwords require a change before archive or management access.

For a local-only development server, set `IIHS_PUBLIC_ORIGIN` to the exact browser
origin and bind FastAPI to `127.0.0.1`. The secure `__Host-` cookie remains enabled;
do not disable it for development. Test whether the chosen browser accepts secure
cookies on the loopback origin. Use HTTPS for a real deployment, keep secrets out of
the frontend and logs, and obtain a deployment/security review before exposure.

## Current limitations

The local auth rate limit is a SQLite-backed per-client limit intended for a local
demonstration, not distributed abuse protection. Registration does not verify email
ownership, and password recovery email is not implemented. Entra live sign-in,
centralised multi-user hosting and live Microsoft account disablement rechecks remain
unverified. See `docs/architecture/stage4g-super-admin-local-authentication.md`.
