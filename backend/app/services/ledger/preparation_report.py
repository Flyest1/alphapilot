"""Korean, local-only preparation report without raw rows or file paths."""

CHECK_LABELS = {
    "account_and_period": "계좌·통화·대상 기간 및 기초/기말 기준일",
    "cash_flows": "입출금·배당·이자 등 외부 현금흐름",
    "fees_and_taxes": "수수료·세금·총액과 순현금의 부호",
    "fx_and_corporate_actions": "환전·주식 입출고·분할 등 기업행사",
    "settlement_and_corrections": "미수·미지급·결제·취소·정정 내역",
    "overlapping_documents": "명세서 누락 기간·겹친 거래·중복 검토",
}
BLOCK_LABELS = {
    "invalid_manifest": "자료 목록의 형식이나 파일을 확인하세요.",
    "missing_account": "실계좌 번호 대신 사용할 일관된 원장 계좌 식별자를 입력하세요.",
    "missing_period": "검증할 시작일과 종료일을 YYYY-MM-DD로 입력하세요.",
    "invalid_observation_time": "종료일이 지난 뒤의 자료 확인 시각을 시간대와 함께 입력하세요.",
    "missing_opening": "기초 잔고 JSON과 그 근거 원본이 필요합니다.",
    "missing_closing": "기말 잔고 JSON과 그 근거 원본이 필요합니다.",
    "invalid_opening": "기초 잔고의 계좌·기준일·정산 기준·원본 해시를 확인하세요.",
    "invalid_closing": "기말 잔고의 계좌·기준일·정산 기준·원본 해시를 확인하세요.",
    "missing_statements": "기간별 CSV 명세서와 명시적 매핑을 등록하세요.",
    "invalid_statement": "CSV/매핑 파일·선언 기간·크기·행 수·상대 경로를 확인하세요.",
    "invalid_statement_rows": (
        "빈 명세서 또는 해석하지 못한 행이 있습니다. " "원본과 매핑을 확인하세요."
    ),
    "repeated_document": "동일 원본이 반복 등록됐습니다. 원본은 유지하고 자료 목록을 확인하세요.",
    "event_outside_period": "선언한 명세서 기간 밖의 거래가 있습니다.",
    "ambiguous_event_date": "계좌 기준일로 확정할 수 없는 거래 시각이 있습니다.",
    "statement_period_gap": "명세서에 선언한 기간이 전체 검증 기간을 덮지 못합니다.",
    "review_issues": "부분 수집 또는 문서 간 중복 의심 거래의 검토가 필요합니다.",
    "replay_issues": "미확인 증거·결제·정정 등으로 원장 재생이 불완전합니다.",
    "balance_mismatch": "계산 잔고와 제공한 기말 잔고에 차이가 있습니다.",
    "reconciliation_failed": "잔고와 거래 자료의 계좌·기간·정정 관계를 다시 확인하세요.",
}


def render_preparation_report(result):
    ready = result["status"] == "ready_for_review"
    lines = [
        "# 운영 원장 자료 준비 점검",
        "",
        "상태: " + ("검토 가능" if ready else "자료 보완 필요"),
        "자료 구분: "
        + ("가상 검증 자료" if result["synthetic"] else "실제 여부를 별도 확인할 자료"),
        "",
        "이 결과는 로컬 사전 점검입니다. 원문 내용의 진실성·전체 거래의 완전성·운영 저장을",
        "인증하지 않습니다. 실제 수익률과 실현손익은 계산하지 않습니다.",
        "",
        "## 보완 항목",
        "",
    ]
    if not result["blockers"]:
        lines.append("- 자동 점검의 차단 항목 없음. 원문·매핑·잔고 근거를 사람이 검토해야 합니다.")
    for issue in result["blockers"]:
        label = BLOCK_LABELS.get(issue["code"], "자료를 확인하세요.")
        if issue["code"] == "unchecked_material":
            label = CHECK_LABELS[issue["check"]] + " 확인이 필요합니다."
        prefix = f"명세서 {issue['document']} — " if "document" in issue else ""
        lines.append(f"- {prefix}{label}")
    lines.extend(["", "## 매핑 검증", ""])
    for document in result["documents"]:
        lines.append(
            f"- 명세서 {document['index']}: 해석된 행 {document['events']}개, "
            f"오류 행 {len(document['errors'])}개"
        )
        for error in document["errors"]:
            fields = ", ".join(error["fields"]) or "거래 필드 조합"
            lines.append(f"  - 데이터 행 {error['row']}: {fields} 확인 필요")
    if not result["documents"]:
        lines.append("- 아직 해석된 명세서가 없습니다.")
    lines.extend(
        ["", f"문서 간 중복 의심 쌍: {result['duplicate_candidates']}개", "", "## 잔고 대사", ""]
    )
    comparison = result["reconciliation"]
    if comparison is None:
        lines.append("기초·기말 잔고와 기간 자료가 준비되지 않아 대사하지 않았습니다.")
    else:
        label = {"matched": "숫자 일치", "mismatch": "차이 있음", "incomplete": "불완전"}
        lines.append(
            f"대사 상태: {label[comparison['status']]}. 차이 = 제공된 기말 잔고 − 계산 잔고."
        )
        lines.append(
            "오류·제외 행이 있으면 부분 자료의 비교입니다. "
            "숫자 일치만으로 완전성을 인정하지 않습니다."
        )
        lines.extend(["", "| 항목 | 통화/종목 | 차이 |", "|---|---|---|"])
        for component, values in comparison["residuals"].items():
            for key, amount in values.items():
                lines.append(f"| {component} | {key} | {amount} |")
        for issue in comparison["issues"]:
            lines.append(f"- 재생 확인 항목: `{issue['reason']}`")
    lines.extend(
        [
            "",
            "## 다음 절차",
            "",
            "1. 보완 항목을 해결하고 새로운 출력 폴더로 점검을 다시 실행합니다.",
            "2. 원문·매핑·잔고와 해시를 대조합니다. 체크 표시는 사용자 확인 기록입니다.",
            "3. 운영 저장 전 기존 원장의 검토 이력·중복 후보와 다시 대조합니다.",
            "4. 별도 import 도구로 저장합니다. 이 명령에는 DB 저장 기능이 없습니다.",
            "",
            "입력 해시는 report.json에 보관합니다. 입력 변경 시 다시 점검합니다.",
            "보고서와 원본은 개인정보를 포함할 수 있는 비공개 로컬 자료이며 암호화되지 않습니다.",
            "",
        ]
    )
    return "\n".join(lines)
