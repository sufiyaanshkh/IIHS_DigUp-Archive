CREATE TABLE oidc_flow_sessions (
    flow_secret_hash TEXT PRIMARY KEY,
    flow_data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX idx_oidc_flow_expiry ON oidc_flow_sessions(expires_at);
