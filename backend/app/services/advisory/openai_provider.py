from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.openai_request_options import build_completion_options
from app.utils.logging import log_external_failure

ADVISORY_DISCLAIMER = " ".join(
    (
        "투자 의사결정 지원 정보이며 수익을 보장하지 않습니다.",
        "자동매매나 주문을 실행하지 않습니다.",
    )
)


class AdvisoryNarrativePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    point_type: Literal["fact", "calculation", "inference", "limitation"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class AdvisoryNarrative(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    summary_evidence_ids: list[str] = Field(default_factory=list, max_length=10)
    key_findings: list[AdvisoryNarrativePoint] = Field(default_factory=list, max_length=10)
    key_risks: list[AdvisoryNarrativePoint] = Field(default_factory=list, max_length=10)
    actions_to_consider: list[AdvisoryNarrativePoint] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    disclaimer: str


class OpenAIAdvisoryProvider:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    def generate_narrative(
        self,
        analysis_type: str,
        context: dict[str, Any],
    ) -> AdvisoryNarrative:
        if self.client is None:
            if not self.api_key:
                raise RuntimeError("OpenAI API key is not configured")
            from openai import OpenAI

            self.client = OpenAI(api_key=self.api_key)
        response_schema = self._response_schema(context)
        profit_taking_instruction = (
            " profit_taking_review에서는 기존 리포트 매수 의견을 반복하거나 결정 근거로 "
            "사용하지 말고, 제공된 독립 결정과 위험·무효화 조건만 설명하세요. 더 높은 수익이 "
            "확실하다는 표현을 금지하고 결정론적 action을 변경하거나 새로운 매도·매수 행동을 "
            "만들지 마세요."
            if analysis_type == "profit_taking_review"
            else ""
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "당신은 투자 의사결정 지원 분석가입니다. 제공된 JSON 근거와 계산값만 "
                    "사용하고 누락된 사실을 추정하지 마세요. guaranteed profit, certain "
                    "return, risk-free, must buy, must sell 표현을 사용하지 마세요. "
                    "매수·매도 주문이나 "
                    "수량을 제안하지 말고 검토 후보, 관찰, 위험, 무효화 조건을 설명하세요. "
                    "key_findings와 key_risks의 각 항목은 fact, calculation, inference, "
                    "limitation 중 하나로 구분하세요. summary와 limitation 이외의 모든 "
                    "항목은 반드시 context의 evidence_id를 하나 이상 인용하세요. summary도 "
                    "summary_evidence_ids에 근거를 인용하세요. 근거 없는 수치나 날짜는 "
                    "쓰지 마세요. 수치는 결정론적 표에서 별도로 제공되므로 summary, findings, "
                    "risks, actions, limitations 문장에는 숫자·날짜·백분율 문자를 전혀 쓰지 "
                    "말고 방향성·상대평가·한계만 서술하세요."
                    f"{profit_taking_instruction}"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"analysis_type": analysis_type, "context": context},
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]
        try:
            for attempt in range(2):
                response = self.client.chat.completions.create(
                    model=self.model,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "AdvisoryNarrative",
                            "schema": response_schema,
                        },
                    },
                    messages=messages,
                    **build_completion_options(self.model),
                )
                message = response.choices[0].message.content
                if not message:
                    raise RuntimeError("OpenAI returned an empty advisory response")
                try:
                    narrative = AdvisoryNarrative.model_validate_json(message)
                    narrative = narrative.model_copy(update={"disclaimer": ADVISORY_DISCLAIMER})
                    self._validate_language(narrative)
                    self._validate_grounding(narrative, context)
                    return narrative
                except ValueError as exc:
                    if attempt == 1:
                        raise
                    messages.extend(
                        [
                            {"role": "assistant", "content": message},
                            {
                                "role": "user",
                                "content": (
                                    "이전 응답이 근거 검증에 실패했습니다. 오류: "
                                    f"{exc}. context에 실제 존재하는 evidence_id와 수치만 "
                                    "사용해 JSON 전체를 다시 생성하세요. 설명 문장에는 숫자·날짜·"
                                    "백분율 문자를 전혀 쓰지 마세요."
                                ),
                            },
                        ]
                    )
        except Exception as exc:
            log_external_failure(
                "openai",
                exc,
                {"operation": "generate_advisory_narrative", "analysis_type": analysis_type},
            )
            raise

    @staticmethod
    def _response_schema(context: dict[str, Any]) -> dict[str, Any]:
        schema = AdvisoryNarrative.model_json_schema()
        schema["properties"]["disclaimer"] = {"const": ADVISORY_DISCLAIMER}
        evidence_ids = sorted(
            {
                str(item.get("evidence_id"))
                for item in context.get("evidence", [])
                if isinstance(item, dict) and item.get("evidence_id")
            }
        )
        if not evidence_ids:
            return schema
        evidence_item_schema = {"type": "string", "enum": evidence_ids}
        schema["properties"]["summary_evidence_ids"]["items"] = evidence_item_schema
        point_schema = schema["$defs"]["AdvisoryNarrativePoint"]
        point_schema["properties"]["evidence_ids"]["items"] = evidence_item_schema
        return schema

    @staticmethod
    def _validate_language(narrative: AdvisoryNarrative) -> None:
        forbidden = (
            "guaranteed profit",
            "certain return",
            "risk-free",
            "must buy",
            "must sell",
            "수익 보장",
            "확실한 수익",
            "무위험",
            "반드시 매수",
            "반드시 매도",
        )
        text = " ".join(
            [
                narrative.summary,
                *(point.text for point in narrative.key_findings),
                *(point.text for point in narrative.key_risks),
                *(point.text for point in narrative.actions_to_consider),
                *narrative.limitations,
            ]
        ).casefold()
        if any(phrase in text for phrase in forbidden):
            raise ValueError("advisory narrative contains forbidden language")

    @staticmethod
    def _validate_grounding(
        narrative: AdvisoryNarrative,
        context: dict[str, Any],
    ) -> None:
        evidence_ids = {
            str(item.get("evidence_id"))
            for item in context.get("evidence", [])
            if isinstance(item, dict) and item.get("evidence_id")
        }
        unknown_summary_ids = set(narrative.summary_evidence_ids) - evidence_ids
        if unknown_summary_ids:
            raise ValueError("advisory narrative references unknown evidence")
        if narrative.summary and not narrative.summary_evidence_ids:
            raise ValueError("advisory narrative summary lacks evidence")
        for point in [
            *narrative.key_findings,
            *narrative.key_risks,
            *narrative.actions_to_consider,
        ]:
            unknown_ids = set(point.evidence_ids) - evidence_ids
            if unknown_ids:
                raise ValueError("advisory narrative references unknown evidence")
            if point.point_type != "limitation" and not point.evidence_ids:
                raise ValueError("advisory narrative point lacks evidence")

        context_numbers = {
            OpenAIAdvisoryProvider._normalize_number(value)
            for value in re.findall(r"-?\d[\d,]*(?:\.\d+)?", json.dumps(context, default=str))
        }
        narrative_text = " ".join(
            [
                narrative.summary,
                *(point.text for point in narrative.key_findings),
                *(point.text for point in narrative.key_risks),
                *(point.text for point in narrative.actions_to_consider),
                *narrative.limitations,
            ]
        )
        for value in re.findall(r"-?\d[\d,]*(?:\.\d+)?", narrative_text):
            if OpenAIAdvisoryProvider._normalize_number(value) not in context_numbers:
                raise ValueError("advisory narrative contains an unsupported number")

    @staticmethod
    def _normalize_number(value: str) -> str:
        normalized = value.replace(",", "")
        try:
            return format(float(normalized), ".12g")
        except ValueError:
            return normalized
