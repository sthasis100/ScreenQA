"""
providers.py - the AI services ScreenQA can talk to (Step 10).

Each entry says how to connect, which API key it needs, which models it offers,
whether it costs money, and - importantly - WHO RECEIVES YOUR DATA.
Step 15 adds a Settings window to choose between them.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)  # frozen = these entries can't be changed by accident
class Provider:
    id: str  # short internal name
    label: str  # name shown to the user
    company: str  # who receives the question and screenshot
    # Which library ai_client.py uses to talk to it:
    #   "gemini"    = Google's official google-genai library
    #   "anthropic" = Anthropic's official anthropic library
    #   "openai"    = any OpenAI-compatible service (e.g. a local Ollama, later)
    api_style: str
    base_url: str | None  # web address of the service (None = the library's default)
    key_env_var: str  # name of the API-key variable in the .env file
    key_url: str  # where to create a key
    models: tuple[str, ...]  # the first one is the default
    free: bool
    privacy_note: str
    # Longest answer to ask for, in tokens (a token is ~3/4 of a word).
    max_output_tokens: int = 16000
    # Extra settings sent with every request to this service (OpenAI-style only).
    extra_options: dict = field(default_factory=dict)
    # Which models accept a "temperature" setting. None = all of them.
    temperature_models: tuple[str, ...] | None = None

    @property
    def default_model(self) -> str:
        return self.models[0]

    def supports_temperature(self, model: str) -> bool:
        return self.temperature_models is None or model in self.temperature_models


GROQ = Provider(
    id="groq",
    label="Groq (free tier)",
    company="Groq",
    api_style="openai",  # Groq offers an OpenAI-compatible service
    base_url="https://api.groq.com/openai/v1",
    key_env_var="GROQ_API_KEY",
    key_url="https://console.groq.com/keys",
    # The only Groq model that can read images (checked Sept 2026).
    models=("qwen/qwen3.8-27b",),
    free=True,
    privacy_note=(
        "Groq's free plan: Groq says it does not keep your requests by default, apart "
        "from temporary safety logs (up to 30 days). Don't send personal information."
    ),
    # Free-plan limits MEASURED on this project (Sept 2026): 1,000 requests/day,
    # 8,000 tokens/minute in total, and only 1,000 ANSWER tokens per minute.
    # Groq refuses any request that asks for more answer room than that, so we
    # ask for at most 900. A multiple-choice answer + explanation used ~400.
    max_output_tokens=900,
    # This model can "think" before answering, but thinking uses up the same
    # small answer allowance - so we switch it off.
    extra_options={"reasoning_effort": "none"},
)

GEMINI = Provider(
    id="gemini",
    label="Google Gemini (free tier)",
    company="Google",
    # KNOWN GOOGLE PROBLEM (Sept 2026): many new accounts only get keys starting
    # with "AQ.", and Google rejects those with ACCESS_TOKEN_TYPE_UNSUPPORTED.
    # Older keys starting with "AIza" work. Nothing in our code can fix that.
    #
    # Google's own library. (Google's "OpenAI-compatible" address does NOT
    # accept "AQ." keys at all, so we don't use it.)
    api_style="gemini",
    base_url=None,
    key_env_var="GEMINI_API_KEY",
    key_url="https://aistudio.google.com/apikey",
    # gemini-3.8-flash: Google's newest free Flash model (can read images).
    # gemini-3.5-flash-lite: faster, with more free requests per day, a bit less clever.
    models=("gemini-3.8-flash", "gemini-3.5-flash-lite"),
    free=True,
    privacy_note=(
        "On the FREE tier, Google may use what you send (text and images) to improve "
        "its products, and human reviewers may see it. Don't send personal information."
    ),
)

CLAUDE = Provider(
    id="anthropic",
    label="Anthropic Claude (paid)",
    company="Anthropic",
    api_style="anthropic",
    base_url=None,
    key_env_var="ANTHROPIC_API_KEY",
    key_url="https://console.anthropic.com/settings/keys",
    models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"),
    free=False,
    privacy_note="Paid per request. By default, Anthropic does not train its models on API data.",
    # Claude Opus 5 and Sonnet 5 reject a temperature setting (error 400); Haiku 4.5 accepts it.
    temperature_models=("claude-haiku-4-5",),
)

# All providers by id, e.g. PROVIDERS["groq"]. The order is the order shown to the user.
PROVIDERS: dict[str, Provider] = {p.id: p for p in (GROQ, GEMINI, CLAUDE)}

# Used until you pick one: free, and new accounts work straight away.
DEFAULT_PROVIDER_ID = "groq"
