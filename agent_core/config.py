"""Configuration loader: YAML config + multi-resume + direction mapping."""

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DirectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    keywords: list[str] = Field(default_factory=list, description="Search keywords")
    resume_file: str = Field(default="", description="Resume file path relative to project root")
    feature_words: list[str] = Field(
        default_factory=list, description="Feature words for prescreening"
    )

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

    @field_validator("rate_limit_seconds")
    @classmethod
    def _rate_limit_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"rate_limit_seconds must be >= 0, got {v}")
        return v


class MatchingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prescreen_top_n: int = Field(default=30, ge=1)
    match_min_score: int = Field(default=50, ge=0, le=100)
    enrich_in_pipeline: bool = Field(default=False)
    enrich_top_n: int = Field(default=10, ge=1)

    @field_validator("match_min_score")
    @classmethod
    def _score_in_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError(f"match_min_score must be 0-100, got {v}")
        return v

    @field_validator("prescreen_top_n")
    @classmethod
    def _top_n_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"prescreen_top_n must be >= 1, got {v}")
        return v


class PrescreenRulesConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    feature_weight: int = Field(default=25, ge=0)
    keyword_weight: int = Field(default=15, ge=0)
    salary_high_multiplier: float = Field(default=1.5, gt=0)
    salary_high_bonus: int = Field(default=5, ge=0)


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: str = Field(default="deepseek")
    model: str = Field(default="deepseek-v4-pro")
    api_key_env: str = Field(default="DEEPSEEK_API_KEY")
    base_url: str = Field(default="https://api.deepseek.com")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, gt=0)


class NotifyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    windows_toast: bool = Field(default=True)
    notify_on_zero_results: bool = Field(default=True)
    interview_reminder_hours: int = Field(default=24, ge=0)


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True)
    interval_hours: int = Field(default=6, ge=1)
    directions: list[str] = Field(default_factory=lambda: ["industrial_ai_agent", "equipment_amr"])
    quiet_hours: list[int] = Field(default_factory=lambda: [0, 7])


class Config(BaseModel):
    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    platforms: dict[str, PlatformConfig] = Field(default_factory=dict)
    directions: dict[str, DirectionConfig] = Field(default_factory=dict)
    company_aliases: dict[str, list[str]] = Field(default_factory=dict)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)
    prescreen_rules: PrescreenRulesConfig = Field(default_factory=PrescreenRulesConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    search_location: str = Field(default="全国")
    min_salary: int = Field(default=6000, ge=0)
    exclude_keywords: list[str] = Field(default_factory=list)
    project_root: Path = Field(default_factory=lambda: Path("."))

    @property
    def api_key(self) -> str:
        return os.environ.get(self.llm.api_key_env, "")


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
        )

    # Search
    search_raw = raw.get("search", {})
    directions: dict[str, DirectionConfig] = {}
    for dname, ddata in search_raw.get("directions", {}).items():
        directions[dname] = DirectionConfig(
            keywords=ddata.get("keywords", []),
            resume_file=ddata.get("resume_file", ""),
            feature_words=ddata.get("feature_words", []),
        )

    cfg = Config(
        platforms=platforms,
        directions=directions,
        company_aliases=raw.get("company_aliases", {}),
        matching=MatchingConfig(**raw.get("matching", {})),
        prescreen_rules=PrescreenRulesConfig(**raw.get("prescreen_rules", {})),
        llm=LLMConfig(**raw.get("llm", {})),
        notify=NotifyConfig(**raw.get("notify", {})),
        schedule=ScheduleConfig(**raw.get("schedule", {})),
        search_location=search_raw.get("location", "全国"),
        min_salary=search_raw.get("min_salary", 6000),
        exclude_keywords=search_raw.get("exclude_keywords", []),
        project_root=project_root,
    )

    return cfg


def load_resume(cfg: Config, direction: str) -> str:
    """Load resume text for a direction, resolving relative to project root."""
    if direction not in cfg.directions:
        available = list(cfg.directions.keys())
        raise ValueError(f"Unknown direction: {direction}. Available: {available}")
    resume_path = cfg.project_root / cfg.directions[direction].resume_file
    if not resume_path.exists():
        raise FileNotFoundError(f"Resume not found: {resume_path}")
    return resume_path.read_text(encoding="utf-8")
