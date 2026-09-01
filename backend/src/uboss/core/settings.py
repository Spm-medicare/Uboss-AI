"""Runtime configuration, read once at start-up.

Every value that differs between a laptop and production lives here and nowhere else, so a
deployment is described by its environment rather than by edits to code.

Two rules this module exists to keep:

* **A secret has no default.** `database_url`, `auth_signing_key` and the AI key are read from
  the environment or the process refuses to start. A working default for a secret is how a
  development key reaches production.
* **Nothing here decides policy.** These are addresses, timeouts and toggles. Who may do what is
  decided by the permission layer against the caller's token, never by a setting.
"""

from functools import lru_cache
from typing import ClassVar, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UBOSS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── identity of this deployment ──────────────────────────────────────────────────────
    environment: Literal["local", "test", "staging", "production"] = "local"
    api_prefix: str = "/api/v1"
    #: Where the web application is served from. Used to build activation and deep links, so a
    #: wrong value produces a link that goes nowhere rather than a silent failure.
    public_base_url: str = "http://localhost:3000"

    # ── data ─────────────────────────────────────────────────────────────────────────────
    #: The application role's connection. It is deliberately *not* the owner role: row-level
    #: security is only a boundary if the connecting role cannot bypass it.
    database_url: SecretStr
    #: The one cross-tenant credential — `uboss_relay`. The outbox worker delivers every
    #: workspace's mail and the scheduler discovers every workspace's schedules, and neither can
    #: do it as `uboss_app`, whose policies correctly show an unbound connection nothing at all.
    #: Optional here because the API process never needs it; the workers refuse to start without
    #: it, with a sentence, rather than polling forever over an empty view.
    relay_database_url: SecretStr | None = None
    database_pool_size: int = Field(default=10, ge=1, le=100)
    redis_url: str = "redis://localhost:6380/0"

    # ── sessions ─────────────────────────────────────────────────────────────────────────
    auth_signing_key: SecretStr
    access_token_minutes: int = Field(default=30, ge=5, le=240)
    refresh_token_days: int = Field(default=14, ge=1, le=90)
    session_idle_minutes: int = Field(default=480, ge=15, le=10080)
    session_rotation_minutes: int = Field(default=60, ge=5, le=1440)
    session_rotation_grace_seconds: int = Field(default=120, ge=30, le=600)
    #: A successful re-authentication only authorises high-risk work for this long. It is
    #: intentionally much shorter than the session lifetime.
    step_up_minutes: int = Field(default=15, ge=5, le=60)
    step_up_ip_limit: int = Field(default=20, ge=5, le=100)
    step_up_membership_limit: int = Field(default=5, ge=3, le=30)
    step_up_window_seconds: int = Field(default=300, ge=60, le=3600)
    invite_token_minutes: int = Field(default=1440, ge=15, le=10080)
    password_reset_token_minutes: int = Field(default=30, ge=10, le=120)
    workspace_challenge_seconds: int = Field(default=180, ge=60, le=600)
    sign_in_ip_limit: int = Field(default=30, ge=5, le=500)
    sign_in_ip_window_seconds: int = Field(default=300, ge=60, le=3600)
    sign_in_account_limit: int = Field(default=10, ge=3, le=100)
    sign_in_account_window_seconds: int = Field(default=900, ge=60, le=86400)
    sign_in_pair_limit: int = Field(default=8, ge=3, le=100)
    sign_in_pair_window_seconds: int = Field(default=300, ge=60, le=3600)

    # ── the AI gateway ───────────────────────────────────────────────────────────────────
    #: Empty means no model is reachable. That is a supported state: the product must say so on
    #: screen and fall back to its deterministic rules, never pretend a model was consulted.
    anthropic_api_key: SecretStr = SecretStr("")
    ai_timeout_seconds: int = Field(default=60, ge=5, le=600)
    ai_max_output_tokens: int = Field(default=8000, ge=256, le=64000)
    ai_base_url: str = "https://api.anthropic.com"

    #: Which model serves which kind of task. Settings, never a literal in domain code or in the
    #: interface — PLAN's forbidden shortcuts name hard-coding a model name specifically, and the
    #: reason is that the next model change would have to find every one of them.
    #:
    #: Column mapping is small, structured and reviewed by a person before anything happens, so
    #: it is served by a fast model. Proposal work is reasoning-heavy and reviewed before it is
    #: published, so it is served by a capable one.
    ai_model_column_mapping: str = "claude-haiku-4-5-20251001"
    ai_model_proposal: str = "claude-sonnet-5"
    #: The Copilot answers while somebody waits, over material already retrieved rather than from
    #: scratch, so a fast model is the right trade — the reasoning is grounding, not invention.
    ai_model_copilot: str = "claude-haiku-4-5-20251001"

    #: Which provider serves every task. One setting, not one per task: a deployment has the
    #: credentials it has, and a policy that could route half the work to a provider with no key
    #: would fail on the half nobody tested.
    #:
    #: `auto` picks whichever has a key, preferring Anthropic — so a deployment with only an
    #: OpenAI key works without being told to, and one with both keeps the models named above.
    ai_provider: Literal["auto", "anthropic", "openai"] = "auto"

    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com"
    #: The OpenAI equivalents of the two models above, on the same reasoning: a fast model for
    #: the small structured job, a capable one for the reasoning-heavy one.
    openai_model_column_mapping: str = "gpt-4.1-mini"
    openai_model_proposal: str = "gpt-4.1"
    openai_model_copilot: str = "gpt-4.1-mini"

    # ── object storage ───────────────────────────────────────────────────────────────────
    #: S3-compatible (PLAN §26). MinIO locally, whatever the deployment provides in production —
    #: the same API either way, so there is no branch in the code for "local".
    s3_endpoint_url: str = "http://localhost:9002"
    s3_bucket: str = "uboss-files"
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")

    #: How long a download link lives. Short, because a link is forwardable — an email, a chat
    #: message, a screenshot — and this is what limits how far a leaked one travels.
    s3_signed_url_seconds: int = Field(default=300, ge=30, le=3600)

    #: The largest upload accepted. Enforced before anything is read, so a large body cannot be
    #: streamed into memory first and rejected afterwards.
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=1024 * 1024 * 1024)

    # ── the durable runtime ──────────────────────────────────────────────────────────────
    temporal_address: str = "localhost:7233"
    temporal_namespace: str = "default"

    # ── telemetry ────────────────────────────────────────────────────────────────────────
    #: Where traces go. Empty means they are created and discarded — the code path that runs on
    #: a laptop is the one that runs in production, and a product that needs a telemetry backend
    #: in order to start is a product nobody can run locally.
    otlp_endpoint: str = ""

    #: How many traces production keeps. A trace per request costs more than it is worth at
    #: scale, and the interesting ones are errors, which a collector keeps regardless. Ignored
    #: outside production, where everything is sampled.
    trace_sample_ratio: float = Field(default=0.1, ge=0.0, le=1.0)

    # ── operational ──────────────────────────────────────────────────────────────────────
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    #: Hosts this API will answer to. A request arriving with any other Host header is refused,
    #: because the Host header is attacker-controlled and must never select a tenant.
    trusted_hosts: str = "localhost,127.0.0.1"
    cors_origins: str = "http://localhost:3000"

    #  ---------------------------------------------------------------- federated sign-in
    #
    #  PLAN §21 and the decision table: *"Identity | Managed provider with MFA now; SAML/OIDC and
    #  SCIM for enterprise."* Each provider is optional and independent — a deployment may enable
    #  none, one or all three. What matters is that an unconfigured provider is a **supported
    #  state**: the API says which are available and the sign-in screen offers only those, because
    #  a button that cannot complete a sign-in is a control that does not do what it says.
    #
    #  Secrets are `SecretStr` so they never reach a log line or an error body by accident.
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    microsoft_client_id: str = ""
    microsoft_client_secret: SecretStr = SecretStr("")
    #: Microsoft's tenant segment. `common` accepts both work and personal accounts; a single
    #: directory's id restricts it to that organisation, which is what most customers want.
    microsoft_tenant: str = "common"
    apple_client_id: str = ""
    #: Apple issues a client *secret* that is itself a signed JWT the integrator generates from a
    #: private key, and it expires. Held as a secret here; minting it is a deployment concern.
    apple_client_secret: SecretStr = SecretStr("")

    #  ---------------------------------------------------------------- outbound mail
    #
    #  1.2.6 — invite, password set, reset and recovery. The outbox records the intent (1.5.3)
    #  and `notifications.mail` delivers it over SMTP. SMTP rather than a provider API because
    #  every organisation already has a mailbox, and a reset link is one small transactional
    #  message — not a campaign that needs deliverability tooling.
    #
    #  Unset is a supported state, not a broken one: the recovery screen says the deployment
    #  cannot send mail rather than claiming an email was sent. That is a fact about the
    #  deployment and reveals nothing about whether an account exists.
    smtp_host: str = ""
    #: 587 is the submission port and gets STARTTLS; 465 opens an implicit TLS socket. Both are
    #: encrypted — `notifications.mail` refuses to send over a plaintext connection either way.
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    #: Who the mail claims to be from. Defaults to the SMTP username, which is almost always
    #: right and is the address the server will let us send as anyway.
    mail_from_address: str = ""
    #: The display name beside the address. Not the product name by accident — a person deciding
    #: whether a reset mail is genuine reads this first.
    mail_from_name: str = "UBOSS AI"

    @property
    def mail_sender(self) -> str:
        """The envelope address, falling back to the account we authenticate as.

        Sending as an address the SMTP account is not authorised for is the most common way a
        correctly-configured server still refuses the message.
        """
        return self.mail_from_address.strip() or self.smtp_username.strip()

    @property
    def mail_is_configured(self) -> bool:
        """True when an invite or a reset link could actually be delivered.

        Read by the recovery routes and shown on the screen. 1.2.6's rule is that the screen
        never says "email sent" unless an email was accepted for delivery — so the honest answer
        when this is false is to say the system cannot send mail yet.

        A host on its own is not enough. Authentication is what a submission server requires, and
        a deployment with a host but no credentials would queue events that could never be
        delivered while telling people to check their inbox.
        """
        return bool(
            self.smtp_host.strip()
            and self.smtp_username.strip()
            and self.smtp_password.get_secret_value().strip()
            and self.mail_sender
        )

    #: Every provider the product knows how to talk to, in the order the sign-in screen shows
    #: them. Separate from `enabled_oauth_providers` because the screen draws all of these and
    #: only enables that subset — a provider missing from the row reads as unsupported, which is
    #: a different and wrong statement from "not set up here".
    supported_oauth_providers: ClassVar[tuple[str, ...]] = ("google", "microsoft", "apple")

    @property
    def enabled_oauth_providers(self) -> tuple[str, ...]:
        """Which federated providers can actually complete a sign-in.

        A provider with no client id or secret is absent from this tuple, so it never reaches the
        sign-in screen. Computed rather than configured as a list: a deployment that sets
        credentials gets the button, and one that does not cannot accidentally advertise it.
        """
        configured = []
        for name, client_id, secret in (
            ("google", self.google_client_id, self.google_client_secret),
            ("microsoft", self.microsoft_client_id, self.microsoft_client_secret),
            ("apple", self.apple_client_id, self.apple_client_secret),
        ):
            if client_id.strip() and secret.get_secret_value().strip():
                configured.append(name)
        return tuple(configured)

    @property
    def storage_is_configured(self) -> bool:
        """True when object storage can actually be reached.

        Read by the readiness probe and by the upload route. An unconfigured store is a
        supported state — the product says files are unavailable rather than accepting an upload
        it cannot keep.
        """
        return bool(
            self.s3_access_key.get_secret_value().strip()
            and self.s3_secret_key.get_secret_value().strip()
        )

    @property
    def resolved_ai_provider(self) -> str:
        """Which provider will actually be asked, or `""` when none can be.

        `auto` prefers Anthropic when both keys are present, because the models named above are
        the ones the prompts were written against. An explicit choice is honoured even when its
        key is missing — the caller then gets "no model is configured", which is the truthful
        answer for a deployment that named a provider it cannot reach, and far easier to diagnose
        than a silent fallback to the other one.
        """
        anthropic = bool(self.anthropic_api_key.get_secret_value().strip())
        openai = bool(self.openai_api_key.get_secret_value().strip())
        match self.ai_provider:
            case "anthropic":
                return "anthropic" if anthropic else ""
            case "openai":
                return "openai" if openai else ""
            case _:
                if anthropic:
                    return "anthropic"
                return "openai" if openai else ""

    @property
    def ai_is_configured(self) -> bool:
        """True when a model can actually be reached.

        Read by the screens that must say plainly whether a proposal came from a model or from
        the deterministic rules alone.
        """
        return bool(self.resolved_ai_provider)

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @field_validator("database_url", "relay_database_url")
    @classmethod
    def refuse_a_synchronous_driver(cls, value: SecretStr | None) -> SecretStr | None:
        """The API is async end to end; a synchronous driver would block the event loop.

        Caught here rather than at the first query, because a URL that works in a shell and
        stalls under load is the worst kind of configuration mistake.
        """
        if value is None:
            return None
        url = value.get_secret_value()
        if not url.startswith("postgresql+psycopg://"):
            raise ValueError("database_url must use the async driver: postgresql+psycopg://…")
        return value

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if not origins or "*" in origins:
            raise ValueError("cors_origins must contain explicit trusted web origins")
        if any(not origin.startswith(("http://", "https://")) for origin in origins):
            raise ValueError("each CORS origin must start with http:// or https://")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The one instance, read at start-up.

    Cached so that configuration cannot change beneath a request mid-flight — a process that
    reloads settings between two queries can serve one request under two different policies.
    """
    return Settings()
