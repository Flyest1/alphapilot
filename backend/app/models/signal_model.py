from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SignalModelVersionReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    model_key: str
    version: str
    config_sha256: str


class SignalModelActiveEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    report_type: str
    trigger_type: Literal["scheduled"]
    decision_at: str
    started_at: str
    ends_at: str
    status: Literal["pending", "collecting", "review_ready", "failed"]
    expected_observation_count: int = Field(ge=0)
    observed_observation_count: int = Field(ge=0)
    excluded_observation_count: int = Field(ge=0)


class SignalModelSamples(BaseModel):
    model_config = ConfigDict(extra="forbid")

    official_scheduled: int | None = Field(default=None, ge=0)
    manual_input_links: int | None = Field(default=None, ge=0)


class SignalModelThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["unconfigured"] = "unconfigured"
    values: None = None


class SignalModelPromotion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    automatic: Literal[False] = False
    eligible: None = None


class SignalModelEvaluationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["signal-model-evaluation-v1"] = "signal-model-evaluation-v1"
    availability: Literal["available", "migration_required"]
    state: Literal["not_configured", "collecting", "review_ready", "unavailable"]
    research_only: Literal[True] = True
    adoption_permitted: Literal[False] = False
    evaluation_window_weeks: Literal[12] = 12
    champion: SignalModelVersionReference | None = None
    challenger: SignalModelVersionReference | None = None
    active_evaluation: SignalModelActiveEvaluation | None = None
    samples: SignalModelSamples
    thresholds: SignalModelThresholds = SignalModelThresholds()
    promotion: SignalModelPromotion = SignalModelPromotion()
