CREATE TABLE users (
    id TEXT PRIMARY KEY,
    entra_tenant_id TEXT NOT NULL,
    entra_object_id TEXT NOT NULL,
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
    UNIQUE (entra_tenant_id, entra_object_id)
);

CREATE INDEX idx_users_role_status ON users(role, status);

CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    session_secret_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    revoked_by TEXT REFERENCES users(id) ON DELETE RESTRICT,
    revocation_reason TEXT
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_expiry_revocation ON sessions(expires_at, revoked_at);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    target_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    before_value TEXT,
    after_value TEXT,
    reason TEXT,
    request_id TEXT,
    outcome TEXT NOT NULL
);

CREATE INDEX idx_audit_timestamp ON audit_events(timestamp);
CREATE INDEX idx_audit_actor ON audit_events(actor_user_id, timestamp);
CREATE INDEX idx_audit_target ON audit_events(target_user_id, timestamp);

CREATE TRIGGER audit_events_no_update
BEFORE UPDATE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;

CREATE TRIGGER audit_events_no_delete
BEFORE DELETE ON audit_events
BEGIN
    SELECT RAISE(ABORT, 'audit events are append-only');
END;
