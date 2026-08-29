"""Configuration loader: YAML config + multi-resume + direction mapping."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _find_dotenv_path() -> Path | None:
    """Resolve .env path with fallbacks: project root, cwd, grandparent."""
    candidates: list[Path] = []
    # 1. Project root (relative to this config.py, works for editable installs)
    base = Path(__file__).resolve().parent.parent
    candidates.append(base / ".env")
    # 2. Current working directory
    candidates.append(Path.cwd() / ".env")
    # 3. Grandparent (for nested package layouts like src/agent_core/config.py)
    candidates.append(base.parent / ".env")
    for p in candidates:
        if p.is_file():
            return p
    return None


def _load_dotenv(dotenv_path: Path | None = None) -> None:
    """Minimal .env loader: reads KEY=VALUE lines, calls os.environ.setdefault.

    Does NOT overwrite existing env vars. Skips comments and blanks.
    No python-dotenv dependency required.
    """
    if dotenv_path is None:
        dotenv_path = _find_dotenv_path()
    if dotenv_path is None or not dotenv_path.is_file():
        return
    with open(dotenv_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            os.environ.setdefault(key, value)


_load_dotenv()


class DirectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keywords: list[str] = Field(default_factory=list, description="Search keywords")
    resume_file: str = Field(default="", description="Resume file path relative to project root")

    @field_validator("resume_file")
    @classmethod
    def _resume_file_not_empty_for_enabled(cls, v: str) -> str:
        # Allow empty string (backward compat), validate path existence at load time
        return v


class PlatformConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False)
    login_method: str = Field(default="import_cookies")
    cookie_path: str = Field(default="")
    rate_limit_seconds: int = Field(default=30, ge=0)  # rate_limit_seconds >= 0
    search_max_pages: int = Field(default=1, ge=1)  # API pages per keyword; 1 = anti-bot safe
    browser_profile_dir: str = Field(default="")  # Zhilian persistent-browser profile

    @field_validator("rate_limit_seconds", "search_max_pages")
    @classmethod
    def _positive_or_zero(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"value must be >= 0, got {v}")
        return v


class MatchingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    match_min_score: int = Field(default=50, ge=0, le=100)
    enrich_in_pipeline: bool = Field(default=False)
    enrich_top_n: int = Field(default=10, ge=1)
    match_flagged_only: bool = Field(
        default=True, description="Only run LLM match on user-flagged (interested) jobs"
    )

    @field_validator("match_min_score")
    @classmethod
    def _score_in_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError(f"match_min_score must be 0-100, got {v}")
        return v

    salary_high_multiplier: float = Field(default=1.5, gt=0)
    salary_high_bonus: int = Field(default=5, ge=0)


_THINKING_EFFORT_VALUES = {"high", "max", "low", "medium", "xhigh"}


class ThinkingConfig(BaseModel):
    """DeepSeek thinking mode configuration.

    When enabled, reasoning_effort + extra_body={"thinking":{"type":"enabled"}}
    are sent to the API. Temperature/top_p are suppressed (not sent) since the
    API ignores them in thinking mode.

    effort values: high, max (direct); low, medium mapped to high by API;
    xhigh mapped to max by API.
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False, description="Enable DeepSeek thinking (chain-of-thought)")
    effort: str = Field(
        default="high",
        description="Reasoning effort: high | max | low | medium | xhigh",
    )

    @field_validator("effort")
    @classmethod
    def _effort_valid(cls, v: str) -> str:
        if v not in _THINKING_EFFORT_VALUES:
            raise ValueError(
                f"thinking.effort must be one of {sorted(_THINKING_EFFORT_VALUES)}, got {v!r}"
            )
        return v


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(default="deepseek")
    model: str = Field(default="deepseek-v4-flash")
    api_key_env: str = Field(default="DEEPSEEK_API_KEY")
    base_url: str = Field(default="https://api.deepseek.com")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=384000, gt=0)
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)


class NotifyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    windows_toast: bool = Field(default=True)


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True)
    interval_hours: int = Field(default=6, ge=1)
    directions: list[str] = Field(default_factory=lambda: ["default"])
    quiet_hours: list[int] = Field(default_factory=lambda: [0, 7])
    reminder_days: int = Field(default=3, ge=1)


class RealtimeConfig(BaseModel):
    """Volcengine Doubao realtime voice (SC2.0) config for mock interview."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=False)
    ws_port: int = Field(default=8766)
    volc_endpoint: str = Field(default="wss://openspeech.bytedance.com/api/v3/realtime/dialogue")
    model: str = Field(default="2.2.0.0")
    voice: str = Field(default="saturn_zh_male_cujingnanyou_tob")
    resource_id: str = Field(default="volc.speech.dialog")
    # Explicit yaml override (legacy); default comes from the VOLC_APP_KEY env
    # var so the secret never ships in a tracked file.
    app_key: str = Field(default="")
    app_key_env: str = Field(default="VOLC_APP_KEY")
    app_id_env: str = Field(default="VOLC_APP_ID")
    access_key_env: str = Field(default="VOLC_ACCESS_KEY")

    @property
    def resolved_app_key(self) -> str:
        """Effective app key: explicit config wins, else the env var."""
        return self.app_key or os.environ.get(self.app_key_env, "")


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)
    directions: dict[str, DirectionConfig] = Field(default_factory=dict)
    company_aliases: dict[str, list[str]] = Field(default_factory=dict)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    realtime: RealtimeConfig = Field(default_factory=RealtimeConfig)
    search_location: str = Field(default="全国")
    min_salary: int = Field(default=6000, ge=0)
    exclude_keywords: list[str] = Field(default_factory=list)
    project_root: Path = Field(default_factory=lambda: Path("."))

    @property
    def api_key(self) -> str:
        return os.environ.get(self.llm.api_key_env, "")

    @property
    def volc_app_id(self) -> str:
        return os.environ.get(self.realtime.app_id_env, "")

    @property
    def volc_access_key(self) -> str:
        return os.environ.get(self.realtime.access_key_env, "")


def load_config(config_path: str = "config.yaml") -> Config:
    """Load configuration from YAML file and environment."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Build config dict for Pydantic validation
    project_root = path.parent.resolve()

    # Platforms
    platforms: dict[str, PlatformConfig] = {}
    for name, pdata in raw.get("platforms", {}).items():
        platforms[name] = PlatformConfig(
            enabled=pdata.get("enabled", False),
            login_method=pdata.get("login_method", "import_cookies"),
            cookie_path=pdata.get("cookie_path", f"data/cookies/{name}.json"),
            rate_limit_seconds=pdata.get("rate_limit_seconds", 30),
            search_max_pages=pdata.get("search_max_pages", 1),
            browser_profile_dir=pdata.get("browser_profile_dir", ""),
        )

    # Search
    search_raw = raw.get("search", {})
    directions: dict[str, DirectionConfig] = {}
    for dname, ddata in search_raw.get("directions", {}).items():
        directions[dname] = DirectionConfig(
            keywords=ddata.get("keywords", []),
            resume_file=ddata.get("resume_file", ""),
        )

    cfg = Config(
        platforms=platforms,
        directions=directions,
        company_aliases=raw.get("company_aliases", {}),
        matching=MatchingConfig(**raw.get("matching", {})),
        llm=LLMConfig(**raw.get("llm", {})),
        notify=NotifyConfig(**raw.get("notify", {})),
        schedule=ScheduleConfig(**raw.get("schedule", {})),
        realtime=RealtimeConfig(**raw.get("realtime", {})),
        search_location=search_raw.get("location", "全国"),
        min_salary=search_raw.get("min_salary", 6000),
        exclude_keywords=search_raw.get("exclude_keywords", []),
        project_root=project_root,
    )

    return cfg


def load_resume(cfg: Config, direction: str) -> str:
    """Load resume text for a direction, resolving relative to project root.

    Resumes are now user-uploaded (no fixed directions). Resolution order:
      1. If `direction` matches a configured direction, use its resume_file.
      2. Else if a 'default' direction is configured, use its resume_file.
      3. Else fall back to the first .txt/.md file in resumes/ — so manual
         'match run' from the dashboard still works even when config.yaml
         hasn't been refreshed (e.g. resume uploaded before server restart).
      4. Else raise FileNotFoundError with a clear message.
    """
    import os

    candidate: Path | None = None
    if direction in cfg.directions and cfg.directions[direction].resume_file:
        candidate = cfg.project_root / cfg.directions[direction].resume_file
    elif "default" in cfg.directions and cfg.directions["default"].resume_file:
        candidate = cfg.project_root / cfg.directions["default"].resume_file

    if candidate is None or not candidate.exists():
        # Fallback: scan resumes/ for any .txt/.md file
        resumes_dir = cfg.project_root / "resumes"
        if resumes_dir.is_dir():
            for name in sorted(os.listdir(resumes_dir)):
                if name.lower().endswith((".txt", ".md")):
                    f = resumes_dir / name
                    if f.is_file():
                        candidate = f
                        break

    if candidate is None or not candidate.exists():
        raise FileNotFoundError(
            "No resume found. Upload one via the dashboard's 「上传简历」 button "
            "(it will be saved to resumes/ and auto-registered in config.yaml)."
        )
    return candidate.read_text(encoding="utf-8")
