CREATE TABLE users_stage4g (
    id TEXT PRIMARY KEY,
    entra_tenant_id TEXT,
    entra_object_id TEXT,
    email TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN (
        'SUPER_ADMIN', 'ADMIN', 'ARCHIVE_OPERATOR', 'REVIEWER', 'EMPLOYEE'
    )),
    status TEXT NOT NULL CHECK (status IN (
        'ACTIVE', 'SUSPENDED', 'DEACTIVATED', 'LOCKED'
    )),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT,
    deactivated_at TEXT,
    deactivated_by TEXT REFERENCES users(id) ON DELETE RESTRICT,
    status_change_reason TEXT,
    CHECK ((entra_tenant_id IS NULL AND entra_object_id IS NULL) OR
           (entra_tenant_id IS NOT NULL AND entra_object_id IS NOT NULL)),
    UNIQUE (entra_tenant_id, entra_object_id)
);

INSERT INTO users_stage4g SELECT * FROM users;
DROP TABLE users;
ALTER TABLE users_stage4g RENAME TO users;
CREATE INDEX idx_users_role_status ON users(role, status);

CREATE TABLE local_credentials (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE RESTRICT,
    email_normalized TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1))
);

CREATE TABLE auth_configuration (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    registration_enabled INTEGER NOT NULL DEFAULT 0 CHECK (registration_enabled IN (0, 1)),
    bootstrap_completed INTEGER NOT NULL DEFAULT 0 CHECK (bootstrap_completed IN (0, 1))
);

INSERT INTO auth_configuration (id, bootstrap_completed)
SELECT 1, CASE WHEN EXISTS (SELECT 1 FROM users WHERE role = 'SUPER_ADMIN')
    OR EXISTS (SELECT 1 FROM audit_events WHERE action = 'bootstrap.super_admin_created'
               AND outcome = 'SUCCESS') THEN 1 ELSE 0 END;

CREATE TABLE local_auth_attempts (
    key TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    window_start INTEGER NOT NULL
);

CREATE TRIGGER users_keep_last_super_admin_update
BEFORE UPDATE OF role, status ON users
WHEN OLD.role = 'SUPER_ADMIN' AND OLD.status = 'ACTIVE'
 AND (NEW.role != 'SUPER_ADMIN' OR NEW.status != 'ACTIVE')
 AND NOT EXISTS (SELECT 1 FROM users WHERE id != OLD.id AND role = 'SUPER_ADMIN' AND status = 'ACTIVE')
BEGIN
    SELECT RAISE(ABORT, 'The last active Super Administrator must be retained');
END;

CREATE TRIGGER users_keep_last_super_admin_delete
BEFORE DELETE ON users
WHEN OLD.role = 'SUPER_ADMIN' AND OLD.status = 'ACTIVE'
 AND NOT EXISTS (SELECT 1 FROM users WHERE id != OLD.id AND role = 'SUPER_ADMIN' AND status = 'ACTIVE')
BEGIN
    SELECT RAISE(ABORT, 'The last active Super Administrator must be retained');
END;
