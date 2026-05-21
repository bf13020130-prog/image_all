CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
  status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  csrf_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_secrets (
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  secret_key TEXT NOT NULL,
  encrypted_value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, secret_key)
);

CREATE TABLE IF NOT EXISTS user_quotas (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  balance INTEGER NOT NULL DEFAULT 0,
  daily_limit INTEGER NOT NULL DEFAULT 0,
  monthly_limit INTEGER NOT NULL DEFAULT 0,
  concurrent_limit INTEGER NOT NULL DEFAULT 1,
  storage_limit_mb INTEGER NOT NULL DEFAULT 10240,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quota_transactions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  amount INTEGER NOT NULL,
  reason TEXT NOT NULL,
  operator_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS global_settings (
  key TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')),
  progress INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL DEFAULT '{}',
  effective_settings_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  error TEXT NOT NULL DEFAULT '',
  storage_bytes INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_user_created ON jobs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS job_events (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  level TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_artifacts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  url TEXT NOT NULL,
  size_bytes INTEGER NOT NULL DEFAULT 0,
  mime_type TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  attachments_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id TEXT PRIMARY KEY,
  actor_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
