from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime, timezone

import httpx2 as httpx

from app.auth.database import connect, migrate
from app.auth.sessions import audit
from app.core.config import Settings


async def resolve_member(tenant_id: str, object_id: str, settings: Settings) -> tuple[str, str]:
    if not settings.client_id or not settings.client_secret:
        raise RuntimeError("Set IIHS_ENTRA_CLIENT_ID and IIHS_ENTRA_CLIENT_SECRET")
    authority = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(authority, data={
            "client_id": settings.client_id,
            "client_secret": settings.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        })
        token_response.raise_for_status()
        token = token_response.json()["access_token"]
        response = await client.get(
            f"https://graph.microsoft.com/v1.0/users/{object_id}",
            params={"$select": "id,displayName,mail,userPrincipalName,userType,accountEnabled"},
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        profile = response.json()
    if profile.get("id", "").lower() != object_id.lower():
        raise ValueError("Microsoft Graph returned a different object ID")
    if profile.get("userType") != "Member" or profile.get("accountEnabled") is not True:
        raise ValueError("Identity is not an enabled internal member")
    display_name = profile.get("displayName")
    email = profile.get("mail") or profile.get("userPrincipalName")
    if not display_name or not email:
        raise ValueError("Microsoft Graph did not return the required profile")
    return display_name, email


def bootstrap(db_path: str | None, tenant_id: str, object_id: str,
              display_name: str, email: str) -> str:
    connection = connect(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if (connection.execute("SELECT bootstrap_completed FROM auth_configuration WHERE id=1").fetchone()[0]
                or connection.execute("SELECT 1 FROM users WHERE role='SUPER_ADMIN' LIMIT 1").fetchone()):
            raise ValueError("A Super Administrator already exists")
        user = connection.execute(
            "SELECT id,status,role FROM users WHERE entra_tenant_id=? AND entra_object_id=?",
            (tenant_id, object_id),
        ).fetchone()
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if user:
            if user["status"] != "ACTIVE":
                raise ValueError("Existing account is not ACTIVE; bootstrap refused")
            connection.execute(
                "UPDATE users SET role='SUPER_ADMIN',email=?,display_name=?,updated_at=? WHERE id=?",
                (email, display_name, now, user["id"]),
            )
            user_id = user["id"]
            before = f'{{"role":"{user["role"]}","status":"ACTIVE"}}'
        else:
            user_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO users(id,entra_tenant_id,entra_object_id,email,display_name,role,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'SUPER_ADMIN','ACTIVE',?,?)",
                (user_id, tenant_id, object_id, email, display_name, now, now),
            )
            before = None
        audit(connection, "bootstrap.super_admin_created", "SUCCESS", target=user_id,
              before=before, after='{"role":"SUPER_ADMIN","status":"ACTIVE"}',
              reason="one_time_cli_bootstrap")
        connection.execute("UPDATE auth_configuration SET bootstrap_completed=1 WHERE id=1")
        connection.commit()
        return user_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


async def run(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    tenant = args.tenant_id
    if not settings.tenant_id or tenant.lower() != settings.tenant_id.lower():
        print("Tenant ID does not match IIHS_ENTRA_TENANT_ID", file=sys.stderr)
        return 1
    try:
        uuid.UUID(tenant)
        object_id = str(uuid.UUID(args.object_id))
        migrate(args.db)
        display_name, email = await resolve_member(tenant, object_id, settings)
    except Exception as exc:
        print(f"Identity verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified IIHS member: {display_name} <{email}> (object {object_id})")
    if input("Type BOOTSTRAP to create the first Super Administrator: ") != "BOOTSTRAP":
        print("Cancelled")
        return 1
    try:
        user_id = bootstrap(args.db, tenant, object_id, display_name, email)
    except Exception as exc:
        print(f"Bootstrap refused: {exc}", file=sys.stderr)
        return 1
    print(f"Initial Super Administrator created: {user_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the initial IIHS Media Archive Super Administrator")
    parser.add_argument("--tenant-id", required=True, help="IIHS Entra tenant UUID")
    parser.add_argument("--object-id", required=True, help="Entra object UUID verified through IIHS IT")
    parser.add_argument("--db", help="auth database path (overrides IIHS_AUTH_DB_PATH)")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
