from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/reach"
    secret_key: str = "dev-secret-change-me"
    # Kept short since tokens live in localStorage with no server-side revocation --
    # a stolen token is usable until it expires. Track a refresh-token flow or
    # httpOnly-cookie session as a separate follow-up to raise this safely.
    access_token_expire_minutes: int = 120
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Publicly reachable base URL for this API. Uploaded logo/badge images are
    # served from here, and the resulting links go straight into emails sent
    # via Microsoft Graph -- so in any non-local environment this MUST be the
    # real public hostname (e.g. https://reach.acme.com), not localhost.
    public_base_url: str = "http://localhost:8000"

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


settings = Settings()
