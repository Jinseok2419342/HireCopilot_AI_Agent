"""
HireCopilot - 통합 관리자 콘솔

실행: streamlit run recruiter.py --server.port 8502
"""

import json
import os
from datetime import datetime, timedelta, timezone

import streamlit as st
from dotenv import load_dotenv

from admin_store import (
    failed_outbox_count,
    list_interview_records,
    pipeline_result_from_dict,
    save_interview_record,
    summarize_records,
    update_pipeline_result,
    update_review_status,
)
from pipeline import (
    KST,
    load_pipeline_config,
    post_to_gas,
    retry_failed_outbox,
    run_pipeline,
)

load_dotenv(override=True)

RECRUITER_PASSWORD = os.getenv("RECRUITER_PASSWORD", "").strip()
RECRUITER_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recruiter_config.json")

DEFAULT_POSITIONS = [
    {"name": "Customer Success Associate (고객 성공 매니저)", "criteria": ""},
    {"name": "Customer Support Specialist (고객 지원 전문가)", "criteria": ""},
    {"name": "Account Manager (어카운트 매니저)", "criteria": ""},
    {"name": "Sales Development Representative (영업 개발 담당)", "criteria": ""},
    {"name": "Operations Coordinator (운영 조정관)", "criteria": ""},
]

ZAPIER_GUIDE_ROWS = [
    {
        "outbox 탭": "outbox_email",
        "코드가 추가하는 행": "timestamp | to | subject | body | from_name",
        "Zapier Trigger": "Google Sheets - New Spreadsheet Row",
        "Zapier Action": "Gmail - Send Email",
        "주요 매핑": "To=to, Subject=subject, Body=body",
    },
    {
        "outbox 탭": "outbox_slack",
        "코드가 추가하는 행": "timestamp | recipient | message",
        "Zapier Trigger": "Google Sheets - New Spreadsheet Row",
        "Zapier Action": "Slack - Send Direct Message",
        "주요 매핑": "User=recipient, Message=message",
    },
    {
        "outbox 탭": "outbox_notion",
        "코드가 추가하는 행": "timestamp | name | database | notes",
        "Zapier Trigger": "Google Sheets - New Spreadsheet Row",
        "Zapier Action": "Notion - Create Database Item",
        "주요 매핑": "Name=name, Notes=notes",
    },
    {
        "outbox 탭": "outbox_docs",
        "코드가 추가하는 행": "timestamp | candidate_name | candidate_email | content",
        "Zapier Trigger": "Google Sheets - New Spreadsheet Row",
        "Zapier Action": "Google Docs - Append Text",
        "주요 매핑": "Document은 Zap에서 고정, Text=content",
    },
    {
        "outbox 탭": "outbox_zoom",
        "코드가 추가하는 행": "timestamp | topic | start_time_iso | duration_min | candidate_name",
        "Zapier Trigger": "Google Sheets - New Spreadsheet Row",
        "Zapier Action": "Zoom - Create Meeting",
        "주요 매핑": "Topic=topic, Start=start_time_iso, Duration=duration_min",
    },
    {
        "outbox 탭": "outbox_scheduled",
        "코드가 추가하는 행": "timestamp | send_after_iso | to | subject | body | candidate_name",
        "Zapier Trigger": "Google Sheets - New Spreadsheet Row",
        "Zapier Action": "Delay Until(send_after_iso) → Notion Find Item → Gmail Send Email",
        "주요 매핑": "Delay Until=send_after_iso, Notion 검색=candidate_name, To=to, Subject=subject, Body=body (Notion 승인 체크 시에만 발송)",
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_recruiter_config() -> dict:
    if os.path.exists(RECRUITER_CONFIG_PATH):
        try:
            with open(RECRUITER_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    default = {"positions": DEFAULT_POSITIONS, "general_criteria": "", "updated_at": ""}
    try:
        with open(RECRUITER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return default


def save_recruiter_config(config: dict) -> None:
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(RECRUITER_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _ok_badge(ok: bool) -> str:
    return "✅ 정상" if ok else "⚠️ 확인 필요"


def _opinion_badge(opinion: str) -> str:
    return {
        "추천": "🟢 추천",
        "보류": "🟡 보류",
        "비추천": "🔴 비추천",
    }.get(opinion or "", opinion or "—")


def _format_record_label(record: dict) -> str:
    payload = record.get("payload") or {}
    name = payload.get("candidate_name") or "이름 없음"
    opinion = _opinion_badge(payload.get("hiring_opinion"))
    position = payload.get("position") or "포지션 없음"
    timestamp = (payload.get("timestamp") or record.get("recorded_at") or "")[:16]
    return f"{timestamp} | {name} | {position} | {opinion}"


def _result_rows(record: dict) -> list[dict]:
    result = record.get("pipeline_result") or {}
    actions = result.get("actions") or []
    rows = []
    for i, item in enumerate(result.get("action_results") or []):
        target = item[0] if len(item) > 0 else ""
        ok = bool(item[1]) if len(item) > 1 else False
        message = item[2] if len(item) > 2 else ""
        action_row = actions[i].get("row", []) if i < len(actions) else []
        rows.append(
            {
                "target": target,
                "status": "성공" if ok else "실패",
                "message": message,
                "row": action_row,
            }
        )
    return rows


def _review_badge(review: dict | None) -> str:
    status = (review or {}).get("status") or "not_required"
    return {
        "pending": "⏳ 승인 대기",
        "approved_sent": "✅ 승인/발송 완료",
        "approved_send_failed": "⚠️ 승인됨 · 발송 실패",
        "rejected_by_admin": "🛑 관리자 반려",
        "held_by_admin": "🟡 추가 보류",
        "not_required": "—",
    }.get(status, status)


def _effective_review(record: dict) -> dict:
    review = record.get("review")
    if review:
        return review
    payload = record.get("payload") or {}
    result = record.get("pipeline_result") or {}
    if payload.get("hiring_opinion") == "추천" and result.get("screening_passed"):
        return {"status": "pending", "note": "", "updated_at": ""}
    return {"status": "not_required", "note": "", "updated_at": ""}


def _scheduled_action_row(record: dict) -> list | None:
    actions = (record.get("pipeline_result") or {}).get("actions") or []
    for action in actions:
        if action.get("target") == "outbox_scheduled":
            return list(action.get("row") or [])
    return None


def _unique_positions(records: list[dict]) -> list[str]:
    positions = sorted(
        {
            (r.get("payload") or {}).get("position", "").strip()
            for r in records
            if (r.get("payload") or {}).get("position", "").strip()
        }
    )
    return positions


def filter_records(
    records: list[dict],
    *,
    query: str = "",
    opinion: str = "전체",
    position: str = "전체",
    screening: str = "전체",
    failed_outbox_only: bool = False,
) -> list[dict]:
    """이름·이메일·포지션 검색 및 운영 필터."""
    filtered = list(records)
    q = query.strip().lower()
    if q:
        filtered = [
            r
            for r in filtered
            if q in (r.get("payload") or {}).get("candidate_name", "").lower()
            or q in (r.get("payload") or {}).get("candidate_email", "").lower()
            or q in (r.get("payload") or {}).get("position", "").lower()
        ]
    if opinion != "전체":
        filtered = [
            r for r in filtered if (r.get("payload") or {}).get("hiring_opinion") == opinion
        ]
    if position != "전체":
        filtered = [
            r for r in filtered if (r.get("payload") or {}).get("position") == position
        ]
    if screening == "통과":
        filtered = [r for r in filtered if (r.get("pipeline_result") or {}).get("screening_passed")]
    elif screening == "실패":
        filtered = [r for r in filtered if not (r.get("pipeline_result") or {}).get("screening_passed")]
    if failed_outbox_only:
        filtered = [r for r in filtered if failed_outbox_count(r) > 0]
    return filtered


def _render_record_filters(records: list[dict], key_prefix: str) -> list[dict]:
    query = st.text_input(
        "🔍 이름·이메일·포지션 검색",
        key=f"{key_prefix}_search",
        placeholder="검색어를 입력하세요",
    )
    with st.expander("필터 옵션", expanded=False):
        positions = _unique_positions(records)
        col1, col2, col3 = st.columns(3)
        with col1:
            st.selectbox("채용 의견", ["전체", "추천", "보류", "비추천"], key=f"{key_prefix}_opinion")
        with col2:
            st.selectbox("포지션", ["전체", *positions], key=f"{key_prefix}_position")
        with col3:
            st.selectbox("자격 심사", ["전체", "통과", "실패"], key=f"{key_prefix}_screening")
        st.checkbox("알림 실패만 보기", key=f"{key_prefix}_failed_only")

    opinion = st.session_state.get(f"{key_prefix}_opinion", "전체")
    position = st.session_state.get(f"{key_prefix}_position", "전체")
    screening = st.session_state.get(f"{key_prefix}_screening", "전체")
    failed_only = st.session_state.get(f"{key_prefix}_failed_only", False)

    filtered = filter_records(
        records,
        query=query,
        opinion=opinion,
        position=position,
        screening=screening,
        failed_outbox_only=failed_only,
    )
    st.caption(f"{len(filtered)}명 표시 (전체 {len(records)}명)")
    return filtered


def _render_record_detail(record: dict) -> None:
    payload = record.get("payload") or {}
    result = record.get("pipeline_result") or {}
    scores = payload.get("scores") or {}

    st.markdown(f"**기록 ID:** `{record.get('record_id', '-')}`")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.write(f"**이름:** {payload.get('candidate_name', '-')}")
        st.write(f"**이메일:** {payload.get('candidate_email', '-')}")
        st.write(f"**포지션:** {payload.get('position', '-')}")
    with col_b:
        st.write(f"**학력:** {payload.get('degree', '-')}")
        st.write(f"**경력:** {payload.get('experience', '-')}")
        st.write(f"**학점:** {payload.get('gpa', '-') or '-'}")
    with col_c:
        st.write(f"**적합도:** {payload.get('fit_level', '-')}")
        st.write(f"**채용 의견:** {_opinion_badge(payload.get('hiring_opinion'))}")
        st.write(f"**최종 검토:** {_review_badge(_effective_review(record))}")
        st.write(f"**종합 점수:** {scores.get('overall', '-')} / 5")

    col_left, col_right = st.columns([2, 1])
    with col_left:
        st.markdown("**평가 요약**")
        st.write(payload.get("summary") or "(요약 없음)")
        if payload.get("hiring_recommendation_reason"):
            st.markdown("**채용 판단 이유**")
            st.write(payload["hiring_recommendation_reason"])
        st.markdown("**추천 다음 단계**")
        st.write(payload.get("recommended_next_step") or "(다음 단계 없음)")
    with col_right:
        st.markdown("**파이프라인**")
        saved = result.get("interview_saved", ["", ""])
        st.write(f"면접 저장: {saved[1] if len(saved) > 1 else '-'}")
        passed = result.get("screening_passed")
        st.write(f"자격 필터: {'✅ 통과' if passed else '🚫 ' + str(result.get('screening_reason', '-'))}")
        st.write(f"분기: {result.get('branch', '-')}")
        review = _effective_review(record)
        if review.get("updated_at"):
            st.caption(f"검토 기록: {review.get('updated_at')} · {review.get('note', '')}")
        fail_n = failed_outbox_count(record)
        if fail_n:
            st.error(f"실패 outbox {fail_n}건")
        else:
            st.success("outbox 정상")

    rubric_labels = {
        "culture_fit": "문화 적합도",
        "customer_response": "고객 응대",
        "ownership": "주인의식",
        "communication": "커뮤니케이션",
        "learning_agility": "학습 민첩성",
    }
    score_cols = st.columns(5)
    for col, (key, label) in zip(score_cols, rubric_labels.items()):
        col.metric(label, f"{scores.get(key, '-')} / 5")

    col_s, col_c = st.columns(2)
    with col_s:
        if payload.get("strengths"):
            st.markdown("**강점**")
            for item in payload["strengths"]:
                st.markdown(f"- {item}")
    with col_c:
        if payload.get("concerns"):
            st.markdown("**우려사항**")
            for item in payload["concerns"]:
                st.markdown(f"- {item}")

    with st.expander("평가 JSON 보기"):
        st.json(payload)
    with st.expander("대화록 보기"):
        st.code(payload.get("transcript") or "(대화록 없음)", language="text")


def _clear_recruiter_ui_state() -> None:
    """로그아웃 시 관리자 UI 전용 세션 키만 정리."""
    for key in (
        "recruiter_positions",
        "interview_detail_select",
        "outbox_detail_select",
        "retry_record_select",
        "instant_record_select",
        "instant_action_select",
        "final_review_select",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if key.startswith(("dash_", "iv_", "ob_")):
            st.session_state.pop(key, None)


# ---------------------------------------------------------------------------
# 시뮬레이션 / 수동 작업 helpers
# ---------------------------------------------------------------------------

SIM_SCENARIOS = {
    "🟢 추천 (Notion 등록 + 합격 메일 예약 + 관리자 알림)": {
        "hiring_opinion": "추천",
        "fit_level": "strong_match",
    },
    "🟡 보류 (2차 면접 준비: Zoom/Docs/Notion)": {
        "hiring_opinion": "보류",
        "fit_level": "needs_human_review",
    },
    "🔴 비추천 (지원자 탈락 메일)": {
        "hiring_opinion": "비추천",
        "fit_level": "weak_match",
    },
    "🚫 자격 미달 — 학점 3.0 이하": {
        "hiring_opinion": "추천",
        "fit_level": "possible_match",
        "gpa": "2.8",
    },
    "🚫 자격 미달 — 이메일 형식 오류": {
        "hiring_opinion": "추천",
        "fit_level": "possible_match",
        "bad_email": True,
    },
}


def _make_sim_payload(scenario: dict, name: str, email: str, position: str) -> dict:
    if scenario.get("bad_email"):
        email = email.replace("@", "_")
    return {
        "project_notice": "관리자 시뮬레이션",
        "candidate_name": name,
        "candidate_email": email,
        "position": position,
        "degree": "학사 (4년제)",
        "gpa": scenario.get("gpa", "3.8"),
        "experience": "1~3년",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores": {
            "culture_fit": 4,
            "customer_response": 4,
            "ownership": 4,
            "communication": 4,
            "learning_agility": 4,
            "overall": 4.0,
        },
        "fit_level": scenario.get("fit_level", "possible_match"),
        "hiring_opinion": scenario["hiring_opinion"],
        "hiring_recommendation_reason": "관리자 콘솔 시뮬레이션으로 생성된 가상 평가입니다.",
        "summary": "관리자 콘솔에서 파이프라인 동작 확인을 위해 생성한 시뮬레이션 기록입니다.",
        "strengths": ["(시뮬레이션) 명확한 의사소통"],
        "concerns": ["(시뮬레이션) 주인의식 근거 부족"],
        "evidence_quotes": [],
        "recommended_next_step": "(시뮬레이션) 사람 면접 검토",
        "transcript": "면접관: (시뮬레이션) 자기소개 부탁드립니다.\n지원자: (시뮬레이션) 안녕하세요, 테스트 지원자입니다.",
    }


def _sim_llm_fn(_prompt: str) -> str:
    return (
        "1. (시뮬레이션) 고객 불만 상황에서 본인의 역할을 STAR 형식으로 설명해 주세요.\n"
        "2. (시뮬레이션) 팀 내 갈등을 조율했던 경험을 말씀해 주세요.\n"
        "3. (시뮬레이션) 새로운 업무를 빠르게 학습한 사례를 알려 주세요."
    )


def _send_scheduled_now(row: list, webhook_url: str) -> tuple[bool, str]:
    """예약 메일(outbox_scheduled 행)을 Delay/Zapier 대기 없이 즉시 발송한다.

    scheduled row: timestamp | send_after_iso | to | subject | body | candidate_name
    email row:     timestamp | to | subject | body | from_name
    """
    email_row = [
        datetime.now(timezone.utc).isoformat(),
        row[2] if len(row) > 2 else "",
        row[3] if len(row) > 3 else "",
        row[4] if len(row) > 4 else "",
        "채용팀",
    ]
    return post_to_gas({"target": "send_email_now", "row": email_row}, webhook_url)


MANUAL_OUTBOX_TARGETS = [
    "outbox_email",
    "outbox_slack",
    "outbox_notion",
    "outbox_docs",
    "outbox_zoom",
    "outbox_scheduled",
]


# ---------------------------------------------------------------------------
# UI sections
# ---------------------------------------------------------------------------

def render_dashboard(records: list[dict]) -> None:
    summary = summarize_records(records)
    cfg = load_pipeline_config()

    st.markdown("### 오늘의 현황")
    cols = st.columns(4)
    cols[0].metric("전체 면접", summary["total"])
    cols[1].metric("추천", summary["recommended"])
    cols[2].metric("보류", summary["hold"])
    cols[3].metric("비추천", summary["rejected"])

    failed_records = [r for r in records if failed_outbox_count(r) > 0]
    if failed_records:
        st.warning(f"알림 전송 실패 {len(failed_records)}건 — **알림/파이프라인** 메뉴에서 재전송하세요.")

    cols2 = st.columns(3)
    cols2[0].metric("자격 통과", summary["screening_passed"])
    cols2[1].metric("자격 미달", summary["screening_failed"])
    cols2[2].metric("알림 실패", summary["failed_outbox"])

    if records:
        st.divider()
        st.markdown("**최근 면접**")
        recent_rows = []
        for record in records[:5]:
            payload = record.get("payload") or {}
            result = record.get("pipeline_result") or {}
            recent_rows.append(
                {
                    "일시": (payload.get("timestamp") or record.get("recorded_at") or "")[:16],
                    "이름": payload.get("candidate_name", ""),
                    "포지션": payload.get("position", ""),
                    "채용 의견": _opinion_badge(payload.get("hiring_opinion")),
                    "최종 검토": _review_badge(_effective_review(record)),
                    "자격": "✅" if result.get("screening_passed") else "🚫",
                    "outbox 실패": failed_outbox_count(record),
                }
            )
        st.dataframe(recent_rows, use_container_width=True, hide_index=True)

    with st.expander("연결 상태 확인"):
        ok_api = bool(os.getenv("OPENAI_API_KEY", "").strip())
        ok_gas = bool(cfg["webhook_url"])
        c1, c2, c3 = st.columns(3)
        c1.write(f"OpenAI: {_ok_badge(ok_api)}")
        c2.write(f"시트 연결: {_ok_badge(ok_gas)}")
        c3.write(
            f"자격 기준: 학점>{cfg['min_gpa']}, "
            f"학점필수{'O' if cfg['require_gpa'] else 'X'}"
        )

    if not records:
        st.info("아직 면접 기록이 없습니다. 지원자가 `app.py`에서 면접을 완료하면 여기에 나타납니다.")


def render_interviews(records: list[dict]) -> None:
    st.markdown("### 지원자 목록")
    if not records:
        st.info("면접을 완료한 지원자가 없습니다.")
        return

    filtered = _render_record_filters(records, "iv")
    if not filtered:
        st.warning("필터 조건에 맞는 기록이 없습니다.")
        return

    overview_rows = []
    for record in filtered:
        payload = record.get("payload") or {}
        result = record.get("pipeline_result") or {}
        overview_rows.append(
            {
                "일시": (payload.get("timestamp") or record.get("recorded_at") or "")[:16],
                "이름": payload.get("candidate_name", ""),
                "이메일": payload.get("candidate_email", ""),
                "포지션": payload.get("position", ""),
                "학점": payload.get("gpa", ""),
                "적합도": payload.get("fit_level", ""),
                "채용 의견": _opinion_badge(payload.get("hiring_opinion")),
                "최종 검토": _review_badge(_effective_review(record)),
                "자격": "✅" if result.get("screening_passed") else "🚫",
                "분기": result.get("branch", ""),
                "outbox 실패": failed_outbox_count(record),
            }
        )
    st.dataframe(overview_rows, use_container_width=True, hide_index=True)

    st.divider()
    selected = st.selectbox(
        "상세 조회할 지원자",
        options=filtered,
        format_func=_format_record_label,
        key="interview_detail_select",
    )
    _render_record_detail(selected)


def render_final_review_queue(records: list[dict]) -> None:
    cfg = load_pipeline_config()
    review_records = [
        record
        for record in records
        if (record.get("payload") or {}).get("hiring_opinion") == "추천"
        and (record.get("pipeline_result") or {}).get("screening_passed")
    ]

    st.markdown("**최종 승인 큐 (Human-in-the-loop)**")
    st.caption("AI가 추천한 후보자도 관리자가 승인해야 최종 합격 메일을 보낼 수 있습니다.")

    if not review_records:
        st.info("최종 승인 대기 후보자가 없습니다.")
        return

    pending_count = sum(
        1
        for record in review_records
        if _effective_review(record).get("status") == "pending"
    )
    sent_count = sum(
        1
        for record in review_records
        if _effective_review(record).get("status") == "approved_sent"
    )
    rejected_count = sum(
        1
        for record in review_records
        if _effective_review(record).get("status") == "rejected_by_admin"
    )

    col_pending, col_sent, col_rejected = st.columns(3)
    col_pending.metric("승인 대기", pending_count)
    col_sent.metric("승인/발송", sent_count)
    col_rejected.metric("반려", rejected_count)

    st.dataframe(
        [
            {
                "상태": _review_badge(_effective_review(record)),
                "이름": (record.get("payload") or {}).get("candidate_name", ""),
                "포지션": (record.get("payload") or {}).get("position", ""),
                "이메일": (record.get("payload") or {}).get("candidate_email", ""),
                "종합 점수": ((record.get("payload") or {}).get("scores") or {}).get("overall", ""),
                "예약 메일": "있음" if _scheduled_action_row(record) else "없음",
            }
            for record in review_records
        ],
        use_container_width=True,
        hide_index=True,
    )

    selected = st.selectbox(
        "검토할 추천 후보자",
        options=review_records,
        format_func=lambda r: f"{_review_badge(_effective_review(r))} | {_format_record_label(r)}",
        key="final_review_select",
    )
    payload = selected.get("payload") or {}
    review = _effective_review(selected)
    scheduled_row = _scheduled_action_row(selected)

    st.markdown(
        f"**{payload.get('candidate_name', '-')}** · "
        f"{payload.get('position', '-')} · "
        f"{payload.get('candidate_email', '-')}"
    )
    st.write(payload.get("hiring_recommendation_reason") or payload.get("summary") or "검토 사유가 없습니다.")
    if review.get("updated_at"):
        st.caption(f"최근 검토: {_review_badge(review)} · {review.get('updated_at')} · {review.get('note', '')}")

    review_note = st.text_area(
        "관리자 메모",
        value=review.get("note", ""),
        placeholder="승인/반려 사유를 남기면 발표 때 의사결정 로그를 보여주기 좋습니다.",
        key=f"review_note_{selected['record_id']}",
        height=80,
    )

    approve_col, hold_col, reject_col = st.columns(3)
    with approve_col:
        if st.button("✅ 승인하고 합격 메일 발송", type="primary", use_container_width=True):
            if not cfg["webhook_url"]:
                st.error("GAS_WEBHOOK_URL이 설정되지 않아 메일 큐를 보낼 수 없습니다.")
            elif not scheduled_row:
                st.error("이 후보자에는 예약 합격 메일(outbox_scheduled)이 없습니다.")
            else:
                ok, msg = _send_scheduled_now(scheduled_row, cfg["webhook_url"])
                status = "approved_sent" if ok else "approved_send_failed"
                note = f"메일 발송 성공: {msg}" if ok else f"메일 발송 실패: {msg}"
                update_review_status(selected["record_id"], status, note=note, reviewer="admin")
                if ok:
                    st.success("관리자 승인 완료. 합격 메일을 즉시 발송했습니다.")
                else:
                    st.error(f"승인은 기록했지만 발송에 실패했습니다: {msg}")
                st.rerun()
    with hold_col:
        if st.button("🟡 추가 보류", use_container_width=True):
            update_review_status(selected["record_id"], "held_by_admin", note=review_note, reviewer="admin")
            st.success("추가 보류 상태로 저장했습니다.")
            st.rerun()
    with reject_col:
        if st.button("🛑 관리자 반려", use_container_width=True):
            update_review_status(selected["record_id"], "rejected_by_admin", note=review_note, reviewer="admin")
            st.success("관리자 반려 상태로 저장했습니다.")
            st.rerun()


def render_outbox(records: list[dict]) -> None:
    st.markdown("### 알림 · 파이프라인")
    if not records:
        st.info("처리할 기록이 없습니다.")
        return

    failed_records = [record for record in records if failed_outbox_count(record) > 0]
    st.caption("재전송 시 면접 기록은 중복 저장되지 않고, 실패한 알림만 다시 보냅니다.")

    render_final_review_queue(records)
    st.divider()

    filtered = _render_record_filters(records, "ob")
    if not filtered:
        st.warning("필터 조건에 맞는 기록이 없습니다.")
        return

    selected = st.selectbox(
        "outbox 상태를 확인할 지원자",
        options=filtered,
        format_func=_format_record_label,
        key="outbox_detail_select",
    )
    payload = selected.get("payload") or {}
    result = selected.get("pipeline_result") or {}
    st.markdown(
        f"**{payload.get('candidate_name', '-')}** · "
        f"{_opinion_badge(payload.get('hiring_opinion'))} · "
        f"분기 `{result.get('branch', '-')}` · "
        f"자격 {'✅' if result.get('screening_passed') else '🚫'}"
    )

    rows = _result_rows(selected)
    if rows:
        failed_rows = [r for r in rows if r["status"] == "실패" and r["target"] != "pipeline_log"]
        if failed_rows:
            st.error(f"실패한 outbox 액션 {len(failed_rows)}건")
        st.dataframe(
            [
                {
                    "target": row["target"],
                    "status": row["status"],
                    "message": row["message"],
                }
                for row in rows
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("전송 row 원본 보기"):
            st.json(rows)
    else:
        st.info("이 기록에는 outbox 전송 결과가 없습니다. (파이프라인 미실행 또는 드라이런 기록일 수 있습니다)")

    st.divider()
    st.markdown("**알림 재전송**")
    if not failed_records:
        st.success("실패한 알림이 없습니다.")
        return

    retry_target = st.selectbox(
        "재전송할 지원자",
        options=failed_records,
        format_func=_format_record_label,
        key="retry_record_select",
    )
    if st.button("실패한 알림 다시 보내기", type="primary", use_container_width=True):
        result = pipeline_result_from_dict(retry_target.get("pipeline_result"))
        if result is None:
            st.error("재전송할 파이프라인 결과를 복원하지 못했습니다.")
            return
        updated = retry_failed_outbox(result)
        update_pipeline_result(retry_target["record_id"], updated)
        st.success("재전송을 시도했습니다. 최신 결과로 새로고침합니다.")
        st.rerun()


def render_simulator(records: list[dict]) -> None:
    st.markdown("### 테스트 도구")
    st.caption("면접 없이 파이프라인을 테스트하거나, Zapier 연결을 점검합니다. (운영자 전용)")
    cfg = load_pipeline_config()

    tab_scenario, tab_instant, tab_manual = st.tabs(
        ["시나리오 실행", "예약/액션 즉시 실행", "수동 outbox 전송"]
    )

    # --- 1) 시나리오 시뮬레이터 ---
    with tab_scenario:
        st.markdown("가상 지원자 payload를 만들어 파이프라인 전체(필터 → 분기 → outbox)를 실행해 봅니다.")
        with st.form("sim_form"):
            scenario_label = st.selectbox("시나리오", options=list(SIM_SCENARIOS.keys()))
            col1, col2 = st.columns(2)
            with col1:
                sim_name = st.text_input("지원자 이름", value="[테스트] 홍길동")
                sim_position = st.text_input("포지션", value="개발자")
            with col2:
                sim_email = st.text_input("지원자 이메일", value=cfg["admin_email"] or "test@example.com")
            mode = st.radio(
                "실행 모드",
                options=["드라이런 (전송 없이 액션 미리보기)", "실제 전송 (GAS → 시트 → Zap)"],
                horizontal=True,
            )
            save_record = st.checkbox("관리자 콘솔 기록에 저장", value=True)
            save_interviews = st.checkbox("interviews 시트에도 행 저장 (실제 전송 시)", value=False)
            run_sim = st.form_submit_button("▶️ 시나리오 실행", use_container_width=True, type="primary")

        if run_sim:
            dry = mode.startswith("드라이런")
            payload = _make_sim_payload(SIM_SCENARIOS[scenario_label], sim_name, sim_email, sim_position)
            result = run_pipeline(
                payload,
                config=cfg,
                llm_fn=_sim_llm_fn,
                skip_outbox=dry,
                skip_interview_save=dry or not save_interviews,
            )

            st.markdown(
                f"**분기:** {_opinion_badge(result.branch) if result.branch in ('추천', '보류', '비추천') else result.branch}"
                f" &nbsp;|&nbsp; **자격 필터:** {'✅ 통과' if result.screening_passed else f'🚫 {result.screening_reason}'}"
            )

            action_rows = [
                {
                    "target": a.target,
                    "row 미리보기": " | ".join(str(v)[:40] for v in a.row),
                }
                for a in result.actions
            ]
            st.markdown("**계획된 액션**" + (" (드라이런 — 전송되지 않음)" if dry else ""))
            st.dataframe(action_rows, use_container_width=True, hide_index=True)

            if not dry:
                st.markdown("**전송 결과**")
                st.dataframe(
                    [
                        {"target": t, "status": "✅ 성공" if ok else "⚠️ 실패", "message": m}
                        for t, ok, m in result.action_results
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

            if save_record:
                record = save_interview_record(payload, result)
                st.success(f"관리자 콘솔 기록에 저장했습니다 (record_id: {record['record_id']}). 새로고침하면 목록에 표시됩니다.")

    # --- 2) 예약/액션 즉시 실행 ---
    with tab_instant:
        st.markdown(
            "예약된 합격 메일(`outbox_scheduled`)을 **Delay/Notion 승인 게이트 없이 즉시 발송**하거나, "
            "기록된 outbox 액션을 그대로 다시 보냅니다."
        )
        if not cfg["webhook_url"]:
            st.warning("GAS_WEBHOOK_URL이 설정되지 않아 전송할 수 없습니다.")
        actionable = [
            r for r in records
            if any(
                a.get("target") != "pipeline_log"
                for a in (r.get("pipeline_result") or {}).get("actions") or []
            )
        ]
        if not actionable:
            st.info("outbox 액션이 기록된 면접이 없습니다. 시나리오 실행 탭에서 기록을 만들어 보세요.")
            outbox_actions = []
        else:
            selected = st.selectbox(
                "지원자 선택",
                options=actionable,
                format_func=_format_record_label,
                key="instant_record_select",
            )
            actions = (selected.get("pipeline_result") or {}).get("actions") or []
            outbox_actions = [a for a in actions if a.get("target") != "pipeline_log"]

        if outbox_actions:
            action = st.selectbox(
                "액션 선택",
                options=outbox_actions,
                format_func=lambda a: f"{a['target']} — " + " | ".join(str(v)[:30] for v in a.get("row", [])[:4]),
                key="instant_action_select",
            )
            row = action.get("row", [])

            if action["target"] == "outbox_scheduled":
                st.markdown(
                    f"- **수신자:** {row[2] if len(row) > 2 else '-'}\n"
                    f"- **제목:** {row[3] if len(row) > 3 else '-'}\n"
                    f"- **원래 예약 시각:** {row[1] if len(row) > 1 else '-'}"
                )
                if st.button("📨 지금 즉시 발송 (예약/승인 생략)", type="primary", use_container_width=True):
                    ok, msg = _send_scheduled_now(row, cfg["webhook_url"])
                    if ok:
                        st.success(f"즉시 발송 완료 — {msg}")
                    else:
                        st.error(f"전송 실패: {msg}")
            else:
                if st.button("♻️ 이 액션 그대로 재전송", use_container_width=True):
                    ok, msg = post_to_gas({"target": action["target"], "row": row}, cfg["webhook_url"])
                    if ok:
                        st.success(f"`{action['target']}` 재전송 완료 — {msg}")
                    else:
                        st.error(f"전송 실패: {msg}")

    # --- 3) 수동 outbox 전송 ---
    with tab_manual:
        st.markdown("필드를 직접 입력해 outbox 행을 보냅니다. 각 전용 Zap이 제대로 연결되었는지 점검할 때 사용하세요.")
        target = st.selectbox("outbox 탭", options=MANUAL_OUTBOX_TARGETS, key="manual_target")
        now_iso = datetime.now(timezone.utc).isoformat()
        row = None

        if target == "outbox_email":
            to = st.text_input("to", value=cfg["admin_email"], key="m_email_to")
            subject = st.text_input("subject", value="[테스트] HireCopilot 수동 전송", key="m_email_subject")
            body = st.text_area("body (HTML 가능)", value="<p>관리자 콘솔 수동 테스트 메일입니다.</p>", key="m_email_body")
            row = [now_iso, to, subject, body, "채용팀"]
        elif target == "outbox_slack":
            recipient = st.text_input("recipient (Slack user ID)", value=cfg["admin_slack"], key="m_slack_rcpt")
            message = st.text_area("message", value="🧪 관리자 콘솔 수동 테스트 메시지입니다.", key="m_slack_msg")
            row = [now_iso, recipient, message]
        elif target == "outbox_notion":
            n_name = st.text_input("name", value="[테스트] 수동 항목", key="m_notion_name")
            n_db = st.text_input("database", value=cfg["notion_database"], key="m_notion_db")
            n_notes = st.text_area("notes", value="관리자 콘솔 수동 테스트 항목입니다.", key="m_notion_notes")
            row = [now_iso, n_name, n_db, n_notes]
        elif target == "outbox_docs":
            d_name = st.text_input("candidate_name", value="[테스트] 홍길동", key="m_docs_name")
            d_email = st.text_input("candidate_email", value="test@example.com", key="m_docs_email")
            d_content = st.text_area("content", value="관리자 콘솔 수동 테스트 문서 내용입니다.", key="m_docs_content")
            row = [now_iso, d_name, d_email, d_content]
        elif target == "outbox_zoom":
            z_topic = st.text_input("topic", value="[테스트] 수동 미팅", key="m_zoom_topic")
            z_minutes = st.number_input("지금부터 몇 분 뒤 시작?", min_value=5, max_value=1440, value=15, key="m_zoom_delay")
            z_duration = st.number_input("duration_min", min_value=10, max_value=180, value=30, key="m_zoom_dur")
            z_name = st.text_input("candidate_name", value="[테스트] 홍길동", key="m_zoom_name")
            start_iso = (datetime.now(KST) + timedelta(minutes=int(z_minutes))).isoformat()
            st.caption(f"start_time_iso: `{start_iso}`")
            row = [now_iso, z_topic, start_iso, int(z_duration), z_name]
        elif target == "outbox_scheduled":
            s_to = st.text_input("to", value=cfg["admin_email"], key="m_sched_to")
            s_subject = st.text_input("subject", value="[테스트] 예약 메일", key="m_sched_subject")
            s_body = st.text_area("body", value="<p>예약 발송 테스트입니다.</p>", key="m_sched_body")
            s_minutes = st.number_input("지금부터 몇 분 뒤 발송?", min_value=1, max_value=10080, value=5, key="m_sched_delay")
            send_after = (datetime.now(KST) + timedelta(minutes=int(s_minutes))).isoformat()
            st.caption(f"send_after_iso: `{send_after}`")
            row = [now_iso, send_after, s_to, s_subject, s_body, "[테스트] 홍길동"]

        if st.button("🚀 전송", type="primary", use_container_width=True, key="manual_send_btn"):
            ok, msg = post_to_gas({"target": target, "row": row}, cfg["webhook_url"])
            if ok:
                st.success(f"`{target}` 전송 완료 — {msg}")
            else:
                st.error(f"전송 실패: {msg}")


SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE"


def render_zapier_guide() -> None:
    st.subheader("⚡ Zapier 연결 가이드")
    st.caption("Zapier를 처음 쓰는 사람도 따라할 수 있도록 단계별로 정리했습니다. 위에서부터 순서대로 진행하세요.")

    # ── 0. 개념 ──────────────────────────────────────────────
    st.markdown("### 0️⃣ Zapier가 뭔가요?")
    st.markdown(
        """
Zapier는 **"A에서 어떤 일이 생기면, 자동으로 B를 실행"** 해주는 자동화 서비스입니다.
코딩 없이 클릭만으로 앱과 앱을 연결합니다.

- **Zap** = 자동화 규칙 1개 (예: "시트에 새 행이 생기면 → 메일을 보낸다")
- **Trigger(트리거)** = 시작 신호. 이 프로젝트에서는 항상 **Google Sheets에 새 행 추가**
- **Action(액션)** = 실제로 할 일. Gmail 발송, Slack 메시지 등

이 프로젝트의 전체 흐름은 이렇습니다:
"""
    )
    st.code(
        "지원자 면접 종료\n"
        "  → 파이썬(pipeline.py)이 판단: 추천? 보류? 비추천?\n"
        "  → 판단 결과에 따라 Google Sheets의 outbox_* 탭에 '할 일'을 행으로 추가\n"
        "  → Zapier가 새 행을 감지 (Trigger)\n"
        "  → 연결된 앱이 실행 (Action: 메일 발송, Slack 알림, Zoom 생성 ...)",
        language="text",
    )
    st.info(
        "💡 판단(누구에게 뭘 보낼지)은 전부 파이썬 코드가 합니다. "
        "Zapier 안에는 조건/분기를 넣지 않고, **탭 1개당 Zap 1개**로 단순하게 연결만 합니다."
    )

    # ── 1. 사전 준비 ─────────────────────────────────────────
    st.markdown("### 1️⃣ 사전 준비 (Zap 만들기 전에)")
    st.markdown(
        f"""
| # | 할 일 | 방법 |
|---|---|---|
| 1 | Zapier 계정 만들기 | [zapier.com](https://zapier.com) 접속 → **Sign up** → Google 계정으로 가입 (팀 공용 Google 계정 추천) |
| 2 | 스프레드시트 열어보기 | [HireCopilot 시트 열기]({SPREADSHEET_URL}) — 접근 권한이 없다면 시트 소유자에게 공유 요청 |
| 3 | **outbox 탭 미리 만들기** | 시트에 `outbox_email` 같은 탭이 아직 없으면 Zapier에서 선택할 수 없습니다. 이 콘솔의 **🧪 시뮬레이션/수동 작업 → 수동 outbox 전송**에서 각 탭으로 테스트 행을 1개씩 보내면 탭이 헤더와 함께 자동 생성됩니다 |
| 4 | 연결할 앱 계정 준비 | Gmail, Slack(워크스페이스), Notion, Zoom 계정 로그인 상태 확인 |
"""
    )
    st.warning(
        "⚠️ 3번이 중요합니다. GAS가 첫 전송 때 탭을 자동 생성하므로, "
        "**Zap을 만들기 전에 수동 전송으로 탭부터 만들어 두세요.** "
        "탭의 1행(헤더: to, subject, body...)을 Zapier가 컬럼 이름으로 인식합니다."
    )

    # ── 2. 공통 순서 ─────────────────────────────────────────
    st.markdown("### 2️⃣ Zap 만들기 공통 순서 (모든 Zap 동일)")
    st.markdown(
        """
1. [zapier.com](https://zapier.com) 로그인 → 왼쪽 위 **+ Create** → **Zaps** 클릭
2. **Trigger** 칸 클릭 → 검색창에 `Google Sheets` 입력 → 선택
3. **Trigger event**: `New Spreadsheet Row` 선택 → **Continue**
4. **Account**: **Sign in** 눌러 Google 계정 연결 (최초 1회만) → **Continue**
5. **Spreadsheet**: `HireCopilot` 시트 선택 / **Worksheet**: 연결할 `outbox_*` 탭 선택 → **Continue**
6. **Test trigger** 클릭 → 탭에 있는 행이 샘플로 보이면 성공 (1️⃣-3에서 보낸 테스트 행이 여기서 쓰입니다)
7. **Action** 칸 클릭 → 아래 **3️⃣ 앱별 설정**에서 해당 앱 부분을 펼쳐 그대로 따라하기
8. **Test step**으로 실제 발송 1회 테스트 → 문제 없으면 오른쪽 위 **Publish** (Zap이 **On**이 되어야 동작합니다!)
"""
    )

    # ── 3. 앱별 설정 ─────────────────────────────────────────
    st.markdown("### 3️⃣ 앱별 Action 설정 (만들 Zap은 총 6개)")
    st.caption("각 항목을 펼치면 필드에 뭘 넣어야 하는지 나옵니다. '←' 왼쪽은 Zapier 입력란, 오른쪽은 시트 컬럼입니다.")

    with st.expander("📧 Zap 1. 탈락/알림 메일 — `outbox_email` → Gmail  (난이도 ★☆☆, 가장 먼저 만드세요)"):
        st.markdown(
            """
**언제 실행되나:** 비추천 지원자 탈락 안내, 관리자 알림 메일

1. Trigger: 공통 순서대로, Worksheet = `outbox_email`
2. Action 앱: `Gmail` → Event: **Send Email** → Gmail 계정 연결
3. 필드 입력 (입력란을 클릭하면 시트 컬럼 목록이 떠서 선택할 수 있습니다):
   - **To** ← `to`
   - **Subject** ← `subject`
   - **Body Type** : `HTML` 로 변경 (본문이 HTML로 만들어지기 때문)
   - **Body** ← `body`
   - **From Name** ← `from_name` (선택)
4. Test → 본인 메일로 수신 확인 → **Publish**
"""
        )

    with st.expander("💬 Zap 2. 관리자 Slack 알림 — `outbox_slack` → Slack  (난이도 ★☆☆)"):
        st.markdown(
            """
**언제 실행되나:** 추천/보류 지원자 발생 시 관리자에게 DM

1. Trigger: Worksheet = `outbox_slack`
2. Action 앱: `Slack` → Event: **Send Direct Message** → Slack 워크스페이스 연결
3. 필드 입력:
   - **To Username**: 목록에서 관리자 선택, 또는 `Custom` 탭에서 ← `recipient` (시트에 Slack 멤버 ID가 들어옵니다. 예: U0123ABC)
   - **Message Text** ← `message`
   - **Send as a bot?**: Yes (기본값)
4. Test → Slack DM 수신 확인 → **Publish**

> 💡 Slack 멤버 ID 찾기: Slack에서 본인 프로필 → ⋯ 더보기 → "멤버 ID 복사".
> 그 값을 `.env`의 `ADMIN_SLACK_USER_ID`에 넣어야 파이프라인이 이 탭에 행을 만듭니다.
"""
        )

    with st.expander("📝 Zap 3. 후보자 Notion 등록 — `outbox_notion` → Notion  (난이도 ★★☆)"):
        st.markdown(
            """
**언제 실행되나:** 추천/보류 지원자를 Notion 데이터베이스에 등록 (관리자 검토 목록)

**먼저 Notion 쪽 준비:**
1. Notion에서 새 페이지 → **데이터베이스(표)** 생성 (예: "채용 후보 검토")
2. 속성(컬럼) 3개 준비:
   - `Name` (제목 속성 — 기본으로 있음)
   - `Notes` (텍스트 속성 — 새로 추가)
   - `승인` (**체크박스** 속성 — 새로 추가. Zap 6의 최종 합격 게이트로 사용!)

**Zapier 설정:**
1. Trigger: Worksheet = `outbox_notion`
2. Action 앱: `Notion` → Event: **Create Database Item** → Notion 연결 (연결 시 위에서 만든 DB 접근 허용 체크)
3. 필드 입력:
   - **Database**: 위에서 만든 DB 선택
   - **Name** ← `name`
   - **Notes** ← `notes`
   - **승인**: 비워두기 (관리자가 나중에 직접 체크)
4. Test → Notion에 항목 생기는지 확인 → **Publish**
"""
        )

    with st.expander("📄 Zap 4. 2차 면접 질문 문서 — `outbox_docs` → Google Docs  (난이도 ★☆☆)"):
        st.markdown(
            """
**언제 실행되나:** 보류 지원자의 AI 생성 2차 면접 질문을 문서에 누적 기록

**먼저:** Google Docs에서 빈 문서 1개 생성 (예: "2차 면접 질문 모음")

1. Trigger: Worksheet = `outbox_docs`
2. Action 앱: `Google Docs` → Event: **Append Text to Document**
3. 필드 입력:
   - **Document Name**: 위에서 만든 문서 선택 (고정)
   - **Text to Append** ← `content`  (앞뒤로 줄바꿈이나 `----` 구분선을 직접 타이핑해 넣으면 보기 좋습니다)
4. Test → 문서에 텍스트 추가 확인 → **Publish**
"""
        )

    with st.expander("🎥 Zap 5. 2차 면접 Zoom 생성 — `outbox_zoom` → Zoom  (난이도 ★★☆)"):
        st.markdown(
            """
**언제 실행되나:** 보류 지원자의 추가 인터뷰 미팅을 자동 생성 (기본: 다음날 오후 2시, 30분)

1. Trigger: Worksheet = `outbox_zoom`
2. Action 앱: `Zoom` → Event: **Create Meeting** → Zoom 계정 연결
3. 필드 입력:
   - **Topic** ← `topic`
   - **When (Start Time)** ← `start_time_iso`  (ISO 형식 시간이 들어있어 그대로 인식됩니다)
   - **Duration (in minutes)** ← `duration_min`
   - **Meeting Type**: `Scheduled Meeting`
4. Test → Zoom 예약 미팅 생성 확인 → **Publish**
"""
        )

    with st.expander("⏰ Zap 6. 최종 합격 메일 (사람 승인 후 예약 발송) — `outbox_scheduled`  (난이도 ★★★, 5단계)"):
        st.markdown(
            """
**언제 실행되나:** 추천 지원자 발생 시. 관리자가 **다음날 오후 2시 전까지 Notion에서 `승인` 체크박스를 켜면**
그 시각에 최종 합격 메일이 자동 발송됩니다. 체크하지 않으면 발송되지 않습니다 (사람이 최종 결정).

> ⚠️ 이 Zap만 5단계짜리입니다. **Zapier 무료 플랜은 2단계(트리거+액션 1개)까지만 지원**하므로
> 유료 플랜(또는 트라이얼)이 필요합니다. 유료가 어렵다면 이 Zap은 생략하고,
> 콘솔의 **🧪 시뮬레이션/수동 작업 → 예약/액션 즉시 실행**에서 관리자가 직접 "지금 즉시 발송"을 눌러도 됩니다.

1. **Trigger**: Google Sheets `New Spreadsheet Row`, Worksheet = `outbox_scheduled`
2. **Action ①**: `Delay by Zapier` → Event: **Delay Until** → **Date/Time** ← `send_after_iso`
   (이 시각까지 기다렸다가 다음 단계 진행)
3. **Action ②**: `Notion` → Event: **Find Database Item** → Database: Zap 3에서 만든 DB
   → 검색 필드: `Name` ← `candidate_name`
4. **Action ③**: `Filter by Zapier` → **Only continue if...**
   → 필드: (Notion 결과의) `승인` → 조건: `(Boolean) Is true`
   (체크 안 됐으면 여기서 멈추고 메일이 나가지 않습니다)
5. **Action ④**: `Gmail` → **Send Email**
   - **To** ← `to` / **Subject** ← `subject` / **Body Type**: HTML / **Body** ← `body`
6. Test 후 **Publish**
"""
        )

    # ── 4. 연결 확인 ─────────────────────────────────────────
    st.markdown("### 4️⃣ 연결이 잘 됐는지 확인하는 법")
    st.markdown(
        """
1. 이 콘솔의 **🧪 시뮬레이션/수동 작업 → 수동 outbox 전송**에서 탭을 골라 테스트 행을 보냅니다
   (받는 사람은 본인 메일/본인 Slack으로!)
2. 잠시 기다리면 연결한 앱에서 실제 동작이 일어납니다
3. 안 오면 Zapier 사이트의 **Zap History**(왼쪽 메뉴)에서 실행 이력과 에러 메시지를 확인하세요
4. 전체 흐름 테스트는 **시나리오 실행 → 실제 전송** 모드로 추천/보류/비추천을 하나씩 돌려보세요
"""
    )

    # ── 5. 자주 막히는 부분 ───────────────────────────────────
    st.markdown("### 5️⃣ 자주 막히는 부분 (FAQ)")
    with st.expander("Q. 시트에 행이 추가됐는데 Zap이 실행을 안 해요"):
        st.markdown(
            """
- Zap이 **Published / On** 상태인지 확인하세요 (만들기만 하고 끄두면 동작 안 함)
- **무료 플랜은 새 행을 즉시 감지하지 않고 일정 주기(약 15분)마다 확인**합니다. 기다려 보세요
- Trigger의 Spreadsheet/Worksheet가 올바른 탭인지 다시 확인하세요
"""
        )
    with st.expander("Q. Worksheet 목록에 outbox 탭이 안 보여요"):
        st.markdown(
            """
탭이 아직 시트에 없는 경우입니다. **수동 outbox 전송**으로 그 탭에 행을 1개 보내면
GAS가 헤더와 함께 탭을 자동 생성합니다. 그 후 Zapier에서 목록 새로고침(↻) 하세요.
"""
        )
    with st.expander("Q. 필드 매핑할 때 컬럼 이름 대신 'Col A, Col B'로 나와요"):
        st.markdown(
            """
탭의 1행이 헤더(`to`, `subject`, ...)가 아닌 경우입니다. GAS가 탭을 자동 생성했다면 헤더가 있어야 정상입니다.
시트에서 1행이 데이터로 덮였는지 확인하고, 필요하면 1행에 헤더를 직접 입력한 뒤 Zap의 Test trigger를 다시 실행하세요.
"""
        )
    with st.expander("Q. 메일이 진짜 지원자에게 갈까 봐 테스트가 무서워요"):
        st.markdown(
            """
- **수동 outbox 전송**: 받는 사람을 본인 메일로 직접 입력하니 안전합니다
- **시나리오 실행 — 드라이런 모드**: 아무것도 전송하지 않고 어떤 행이 만들어질지만 미리 봅니다
- **시나리오 실행 — 실제 전송**: 지원자 이메일 칸에 본인 메일을 넣고 돌리세요
"""
        )
    with st.expander("Q. Zap 6(최종 합격)이 무료 플랜에서 안 만들어져요"):
        st.markdown(
            """
정상입니다 — 무료 플랜은 다단계 Zap을 지원하지 않습니다. 두 가지 선택지가 있습니다:
1. Zapier 유료 플랜(트라이얼 포함) 사용
2. Zap 6 없이 운영: 관리자가 이 콘솔의 **예약/액션 즉시 실행**에서 검토 후 직접 "지금 즉시 발송" 클릭
   (사람이 승인한다는 점은 동일하고, 자동 예약만 수동으로 바뀝니다)
"""
        )

    # ── 6. 요약 표 ───────────────────────────────────────────
    st.divider()
    st.markdown("### 📋 요약: 만들어야 할 Zap 한눈에 보기")
    st.dataframe(ZAPIER_GUIDE_ROWS, use_container_width=True, hide_index=True)

    st.markdown("**참고: 채용 의견별로 어떤 outbox가 생기나**")
    st.dataframe(
        [
            {
                "채용 의견": "🟢 추천",
                "생성 outbox": "outbox_notion, outbox_scheduled(최종 합격 메일 예약), outbox_slack, outbox_email(관리자 알림)",
                "의도": "관리자가 Notion에서 승인 체크하면 예약된 최종 합격 메일 발송 (HITL)",
            },
            {
                "채용 의견": "🟡 보류",
                "생성 outbox": "outbox_slack, outbox_email, outbox_notion, outbox_zoom, outbox_docs",
                "의도": "추가 면접 준비와 관리자 검토",
            },
            {
                "채용 의견": "🔴 비추천",
                "생성 outbox": "outbox_email",
                "의도": "지원자에게 결과 안내 메일 발송",
            },
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_filter_settings(config: dict) -> None:
    st.subheader("🚦 자격 필터 (2차 파이프라인)")
    st.caption(
        "면접 종료 후 outbox 큐잉 전에 적용되는 자동 필터입니다. "
        "여기서 저장한 값이 .env의 PIPELINE_* 설정보다 우선하며, 재시작 없이 다음 면접부터 반영됩니다."
    )

    effective = load_pipeline_config()

    col_f1, col_f2 = st.columns([1, 1])
    with col_f1:
        filter_min_gpa = st.number_input(
            "학점 커트라인 (이 값 초과만 통과, 동점은 탈락)",
            min_value=0.0,
            max_value=4.5,
            value=float(effective["min_gpa"]),
            step=0.1,
            format="%.1f",
            key="filter_min_gpa_input",
        )
    with col_f2:
        filter_require_gpa = st.checkbox(
            "학점 미입력 시 탈락",
            value=bool(effective["require_gpa"]),
            key="filter_require_gpa_input",
            help="끄면 학점을 입력하지 않은 지원자도 통과합니다 (입력했다면 커트라인은 그대로 적용). 지원자 온보딩의 학점 필수 표시도 함께 바뀝니다.",
        )
        filter_block_newgrad = st.checkbox(
            "신입(경력 없음) 지원자 탈락",
            value=bool(effective["block_newgrad"]),
            key="filter_block_newgrad_input",
        )

    st.info(
        f"현재 적용 중: 학점 > **{effective['min_gpa']}** · "
        f"학점 필수 **{'ON' if effective['require_gpa'] else 'OFF'}** · "
        f"신입 제외 **{'ON' if effective['block_newgrad'] else 'OFF'}**"
    )

    st.markdown("**고정 필터 (항상 적용)**")
    st.markdown(
        "- 이메일에 `@` 포함\n"
        "- 학위 입력 (\"없음\"은 탈락)\n"
        "- 경력 입력 (\"없음\"은 탈락)"
    )

    if st.session_state.pop("filter_settings_saved", False):
        st.success("자격 필터가 저장되었습니다. 다음 면접부터 적용됩니다.")

    if st.button("필터 저장", use_container_width=True, type="primary", key="save_filters_btn"):
        save_recruiter_config(
            {
                "positions": config.get("positions", []),
                "general_criteria": config.get("general_criteria", ""),
                "pipeline": {
                    "min_gpa": float(filter_min_gpa),
                    "require_gpa": bool(filter_require_gpa),
                    "block_newgrad": bool(filter_block_newgrad),
                },
            }
        )
        st.session_state["filter_settings_saved"] = True
        st.rerun()


def render_recruiting_settings(config: dict) -> None:
    st.subheader("채용 담당 설정")
    st.caption("지원 포지션과 포지션별 AI 면접 중점 평가 기준을 관리합니다.")

    if "recruiter_positions" not in st.session_state:
        st.session_state.recruiter_positions = list(config.get("positions", []))

    with st.expander("새 포지션 추가"):
        new_pos_name = st.text_input(
            "포지션 이름",
            key="new_pos_name_input",
            placeholder="예: IT 개발자, 마케팅 담당자",
        )
        new_pos_criteria = st.text_area(
            "중점 평가 기준",
            key="new_pos_criteria_input",
            height=100,
            placeholder="이 포지션에서 중요하게 보는 역량, 경험, 태도 등을 자유롭게 서술하세요.",
        )
        if st.button("포지션 추가", key="add_pos_btn"):
            if new_pos_name.strip():
                st.session_state.recruiter_positions.append(
                    {"name": new_pos_name.strip(), "criteria": new_pos_criteria.strip()}
                )
                st.rerun()
            else:
                st.error("포지션 이름을 입력하세요.")

    if st.session_state.recruiter_positions:
        for i, pos in enumerate(st.session_state.recruiter_positions):
            with st.expander(f"{pos['name']}", expanded=True):
                updated_name = st.text_input("포지션 이름", value=pos["name"], key=f"pos_name_{i}")
                updated_criteria = st.text_area(
                    "중점 평가 기준",
                    value=pos.get("criteria", ""),
                    key=f"pos_criteria_{i}",
                    height=120,
                )
                col_save, col_del = st.columns([3, 1])
                with col_save:
                    if st.button("수정 저장", key=f"update_pos_{i}"):
                        st.session_state.recruiter_positions[i] = {
                            "name": updated_name.strip(),
                            "criteria": updated_criteria.strip(),
                        }
                        st.rerun()
                with col_del:
                    if st.button("삭제", key=f"del_pos_{i}"):
                        st.session_state.recruiter_positions.pop(i)
                        st.rerun()
    else:
        st.info("등록된 포지션이 없습니다. 위에서 포지션을 추가하세요.")

    st.divider()
    st.markdown("**공통 채용 중점 사항**")
    general_criteria = st.text_area(
        "모든 포지션에 공통으로 적용될 채용 기준",
        value=config.get("general_criteria", ""),
        height=120,
        placeholder="예: 팀워크와 커뮤니케이션을 중시합니다. 자기 주도적 학습 능력을 가진 인재를 선호합니다.",
        key="general_criteria_input",
    )

    if st.session_state.pop("recruiter_settings_saved", False):
        st.success("채용 설정이 저장되었습니다. 다음 면접부터 적용됩니다.")

    if st.button("설정 저장", use_container_width=True, type="primary"):
        save_recruiter_config(
            {
                "positions": st.session_state.recruiter_positions,
                "general_criteria": general_criteria.strip(),
                # 자격 필터는 별도 탭에서 관리 — 기존 값 보존
                "pipeline": config.get("pipeline") or {},
            }
        )
        st.session_state["recruiter_settings_saved"] = True
        st.rerun()

    if config.get("updated_at"):
        st.caption(f"마지막 저장: {config['updated_at']}")


# ---------------------------------------------------------------------------
# App shell
# ---------------------------------------------------------------------------

_NAV_ITEMS = [
    "📊 대시보드",
    "🧑‍💼 지원자 목록",
    "📤 알림/파이프라인",
    "🧪 테스트 도구",
    "⚡ Zapier 연결",
    "⚙️ 설정",
]

st.set_page_config(
    page_title="HireCopilot — 관리자",
    page_icon="👔",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    div[data-testid="stMetric"] {
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.18);
        border-radius: 14px;
        padding: 16px 18px;
    }
    div[data-testid="stMetricValue"] { font-weight: 700; font-size: 1.6rem; }
    div[data-testid="stSidebar"] { background: var(--secondary-background-color); }
    .rc-hero {
        background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 60%, #60a5fa 100%);
        padding: 24px 28px;
        border-radius: 18px;
        margin-bottom: 20px;
        color: #fff;
    }
    .rc-hero h1 { margin: 0; font-size: 1.5rem; }
    .rc-hero p { margin: 6px 0 0; opacity: 0.9; font-size: 0.9rem; }
    .rc-login {
        max-width: 400px;
        margin: 60px auto;
        padding: 36px 32px;
        border-radius: 20px;
        background: var(--secondary-background-color);
        border: 1px solid rgba(128,128,128,0.2);
        box-shadow: 0 4px 24px rgba(0,0,0,0.06);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

if not st.session_state.get("recruiter_authenticated"):
    st.markdown(
        '<div class="rc-login">'
        '<h2 style="text-align:center;margin-top:0;">👔 채용 관리자</h2>'
        '<p style="text-align:center;opacity:0.7;">HireCopilot 관리자 콘솔</p>'
        '</div>',
        unsafe_allow_html=True,
    )
    _, col, _ = st.columns([1, 1.2, 1])
    with col:
        if not RECRUITER_PASSWORD:
            st.caption("암호가 설정되지 않아 바로 들어갈 수 있습니다.")
        pw = st.text_input("암호", type="password", key="recruiter_login_pw", label_visibility="collapsed", placeholder="암호 입력")
        if st.button("로그인", key="recruiter_login_btn", use_container_width=True, type="primary"):
            if (RECRUITER_PASSWORD and pw == RECRUITER_PASSWORD) or not RECRUITER_PASSWORD:
                st.session_state.recruiter_authenticated = True
                st.rerun()
            else:
                st.error("암호가 올바르지 않습니다.")
    st.stop()

config = load_recruiter_config()
records = list_interview_records(limit=100)

with st.sidebar:
    st.markdown("### HireCopilot")
    st.caption("채용 관리자")
    st.divider()
    page = st.radio(
        "메뉴",
        _NAV_ITEMS,
        label_visibility="collapsed",
        key="recruiter_nav",
    )
    st.divider()
    st.caption(f"면접 기록 {len(records)}건")
    if st.button("🔄 새로고침", use_container_width=True):
        st.rerun()
    if st.button("로그아웃", key="recruiter_logout", use_container_width=True):
        st.session_state.recruiter_authenticated = False
        st.session_state.pop("recruiter_nav", None)
        _clear_recruiter_ui_state()
        st.rerun()

st.markdown(
    """
    <div class="rc-hero">
      <h1>👔 채용 관리자 콘솔</h1>
      <p>면접 결과 확인 · 알림 관리 · 채용 설정</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if page == "📊 대시보드":
    render_dashboard(records)
elif page == "🧑‍💼 지원자 목록":
    render_interviews(records)
elif page == "📤 알림/파이프라인":
    render_outbox(records)
elif page == "🧪 테스트 도구":
    render_simulator(records)
elif page == "⚡ Zapier 연결":
    render_zapier_guide()
elif page == "⚙️ 설정":
    tab_recruit, tab_filter = st.tabs(["채용 기준", "자격 필터"])
    with tab_recruit:
        render_recruiting_settings(config)
    with tab_filter:
        render_filter_settings(config)
