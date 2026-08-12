from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/reach"
    secret_key: str = "dev-secret-change-me"
    # Kept short since tokens live in localStorage with no server-side revocation --
    # a stolen token is usable until it expires. Track a refresh-token flow or
    # httpOnly-cookie session as a separate follow-up to raise this safely.
    access_token_expire_minutes: int = 120
    # Self-service forgot/reset-password flow (P1.7) -- deliberately much
    # shorter than the session token above: a reset link only needs to
    # survive the trip from inbox to browser, not a working session.
    password_reset_token_ttl_minutes: int = 30
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Publicly reachable base URL for this API. Uploaded logo/badge images are
    # served from here, and the resulting links go straight into emails sent
    # via Microsoft Graph -- so in any non-local environment this MUST be the
    # real public hostname (e.g. https://reach.acme.com), not localhost.
    public_base_url: str = "http://localhost:8000"
    # Base URL of the Reach *frontend* (the React SPA) -- distinct from
    # public_base_url above (this API's own host). Password-reset links
    # (P1.7) point here, since the reset form is a frontend route the
    # recipient's browser navigates to, not an API endpoint.
    frontend_base_url: str = "http://localhost:5173"

    # Off by default: seeding a known admin@reach.io/Admin@123 account on every
    # startup is only for local dev/demo use. Never enable in production.
    seed_default_admin: bool = False

    # Office 365 / Microsoft Graph (client-credentials) email sending
    azure_tenant_id: str = ""
    o365_client_id: str = ""
    o365_client_secret: str = ""
    o365_from_email: str = ""

    # Metamorph Systems bulk-SMS HTTP gateway
    sms_username: str = ""
    sms_password: str = ""
    sms_template_id: str = ""
    sms_from: str = ""
    sms_api_url: str = "https://www.metamorphsystems.com/index.php/api/bulk-sms"
    sms_success_token: str = ""  # optional substring in the response body that means success

    # Queue-based sending (C2)
    redis_url: str = "redis://localhost:6379/0"
    # Conservative defaults pending confirmed rate caps from Metamorph Systems / Microsoft
    # Graph support -- override via .env once real numbers are known.
    email_rate_per_second: float = 5.0
    sms_rate_per_second: float = 5.0
    send_max_retries: int = 3

    # GET /api/admin/queue-status: how stale a worker's last RQ heartbeat can
    # get before it's reported as "not responding" -- much shorter than RQ's
    # own worker registration TTL (7 min default), which exists to eventually
    # forget a dead worker, not to promptly detect one.
    worker_heartbeat_stale_seconds: int = 90
    # A "sending" campaign with no Message row touched in this many minutes
    # (and past this age itself, for campaigns with no messages processed
    # yet) is flagged as stuck rather than just slow.
    stuck_campaign_minutes: int = 15

    # OpenAI: enhances dataset-validation column-mapping and fix suggestions.
    # Leave blank to use the deterministic heuristic (alias table + fuzzy
    # match / domain-typo dictionary) only -- same "blank creds = simulated"
    # pattern as email/SMS above. A slow/erroring call always falls back to
    # the heuristic rather than failing the upload.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Dataset validation (AI Smart Data Validation): synchronous processing
    # only for now, so caps keep a single request fast. Revisit if real
    # uploads need the async path described in the PRD.
    dataset_validation_max_rows: int = 20_000
    dataset_validation_max_file_mb: float = 25.0
    dataset_validation_session_ttl_minutes: int = 120

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def email_configured(self) -> bool:
        return all([self.azure_tenant_id, self.o365_client_id,
                    self.o365_client_secret, self.o365_from_email])

    @property
    def sms_configured(self) -> bool:
        return all([self.sms_username, self.sms_password, self.sms_from, self.sms_api_url])

    @property
    def ai_suggestions_configured(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
