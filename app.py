"""
HireCopilot - AI 채용 인터뷰 챗봇 (학교 프로젝트 MVP)

지원자가 AI 면접관과 대화하는 Streamlit 앱입니다.
면접 종료 후 평가 JSON을 생성하고 pipeline.py가 GAS 웹훅으로
interviews 시트 저장 + outbox 시트 큐잉을 수행합니다.
(Zapier는 outbox 시트 New Row → Gmail/Slack 등 앱 연결 전용)

본 앱은 학교 수업용 프로토타입입니다.
AI 출력은 사람 검토를 돕기 위한 참고 자료일 뿐입니다.
"""

import json
import os
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv

from admin_store import save_interview_record
from pipeline import (
    PipelineResult,
    load_pipeline_config,
    retry_failed_outbox,
    run_pipeline,
)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

load_dotenv(override=True)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
DEV_TOGGLE_PASSWORD = os.getenv("DEV_TOGGLE_PASSWORD", "").strip()

# If no API key is set, run in DUMMY mode so the UI still works in class.
DUMMY_MODE = not OPENAI_API_KEY

# OpenAI 클라이언트는 필요할 때만 import (추후 Anthropic으로 쉽게 교체 가능)
_openai_client = None
if not DUMMY_MODE:
    try:
        from openai import OpenAI

        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:  # pragma: no cover - defensive
        st.warning(f"OpenAI 클라이언트 초기화 실패, 데모 모드로 전환합니다: {e}")
        DUMMY_MODE = True


# ---------------------------------------------------------------------------
# 회사 인재상 및 평가 루브릭
# ---------------------------------------------------------------------------
# 아래 내용을 자유롭게 수정해서 사용하세요.

COMPANY_PROFILE = """
회사: BrightCare (학교 프로젝트용 가상의 고객경험 전문 기업).

핵심 가치:
- 고객 우선: 고객의 말을 끝까지 경청하고 공감으로 응대한다.
- 주인의식: 문제를 발견하면 해결될 때까지 끝까지 책임진다.
- 빠른 학습: 피드백을 적극적으로 수용하고 빠르게 개선한다.
- 명확한 소통: 동료와 고객에게 친절하고 분명하게 의사를 전달한다.
- 팀 우선 문화: 겸손하고, 호기심이 많고, 서로 돕는다.

채용 포지션: Customer Success Associate (고객 성공 매니저).
"""

RUBRIC = {
    "culture_fit": "회사 인재상과의 적합도 (고객 우선, 겸손, 팀워크 중시).",
    "customer_response": "실제 상황에서의 고객 응대 마인드와 문제 해결 능력.",
    "ownership": "주인의식과 자발성, 끝까지 마무리하는 태도.",
    "communication": "답변의 명확성, 구조화, 공감 표현.",
    "learning_agility": "피드백 수용력과 빠른 적응 능력.",
}

# 학교 데모용으로 짧게 유지하기 위한 한도.
MIN_ANSWERS = 6
MAX_ANSWERS = 8

ALLOWED_FIT_LEVELS = ["strong_match", "possible_match", "needs_human_review", "weak_match"]

PROJECT_NOTICE = "프로토타입"

# 기본 포지션 목록 — recruiter_config.json이 없을 때 파일을 이 값으로 자동 초기화합니다.
DEFAULT_POSITIONS = [
    {"name": "Customer Success Associate (고객 성공 매니저)", "criteria": ""},
    {"name": "Customer Support Specialist (고객 지원 전문가)", "criteria": ""},
    {"name": "Account Manager (어카운트 매니저)", "criteria": ""},
    {"name": "Sales Development Representative (영업 개발 담당)", "criteria": ""},
    {"name": "Operations Coordinator (운영 조정관)", "criteria": ""},
]

DEGREE_OPTIONS = [
    "고졸",
    "전문학사 (2년제)",
    "학사 (4년제)",
    "석사",
    "박사",
    "재학 중",
    "기타",
]

EXPERIENCE_OPTIONS = [
    "신입 (경력 없음)",
    "1년 미만",
    "1~3년",
    "3~5년",
    "5~10년",
    "10년 이상",
]

RECRUITER_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recruiter_config.json")


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

def _build_interview_prompt(candidate_position: str = "", recruiter_config: dict | None = None) -> str:
    """채용 담당자 설정과 지원 포지션을 반영한 면접 시스템 프롬프트를 생성합니다."""
    config = recruiter_config or {}
    positions_list = config.get("positions", [])
    general_criteria = config.get("general_criteria", "").strip()

    role_criteria = ""
    for p in positions_list:
        if p.get("name", "") == candidate_position:
            role_criteria = p.get("criteria", "").strip()
            break

    if positions_list:
        company_section = "현재 채용 중인 포지션 및 채용 기준:\n"
        for p in positions_list:
            company_section += f"- {p['name']}"
            if p.get("criteria"):
                company_section += f": {p['criteria']}"
            company_section += "\n"
        if general_criteria:
            company_section += f"\n공통 채용 중점 사항:\n{general_criteria}\n"
    else:
        company_section = COMPANY_PROFILE

    role_section = ""
    if role_criteria:
        role_section = f"\n이번 면접 지원 포지션: {candidate_position}\n해당 포지션 중점 사항: {role_criteria}"
    elif candidate_position:
        role_section = f"\n이번 면접 지원 포지션: {candidate_position}"

    return f"""당신은 한국 기업의 신입/경력 채용 스크리닝 인터뷰를 진행하는 AI 면접관입니다.
본 인터뷰는 학교 수업용 프로토타입이며 실제 채용 결정에 사용되지 않습니다.
모든 대화는 반드시 한국어(존댓말)로 진행하세요.

{company_section}{role_section}

평가 루브릭 (지원자에게 점수는 공개하지 마세요):
- culture_fit: {RUBRIC['culture_fit']}
- customer_response: {RUBRIC['customer_response']}
- ownership: {RUBRIC['ownership']}
- communication: {RUBRIC['communication']}
- learning_agility: {RUBRIC['learning_agility']}

진행 규칙:
1. 한 번에 하나의 질문만 하세요. 질문은 간결하고 명확하게 작성합니다.
2. 따뜻한 인사와 함께 자기소개와 지원 포지션에 대한 관심을 묻는 질문으로 시작하세요.
3. 특정 평가 항목에 대한 근거가 부족하면 후속 질문(꼬리질문)을 하세요.
   가능하면 행동 기반 질문(STAR: 상황-과제-행동-결과)을 사용하세요.
   예: "~~한 경험에 대해 구체적으로 말씀해 주세요."
4. 인터뷰 전체에서 다섯 가지 루브릭 항목을 모두 다루세요.
5. 지원자 답변 총 {MIN_ANSWERS}~{MAX_ANSWERS}개 정도로 진행합니다.
   모든 항목에 충분한 근거가 모이면 조금 더 일찍 마무리해도 좋습니다.
6. 인터뷰를 종료할 때는 반드시 마지막 줄에 정확히 다음 토큰만 단독으로 출력하세요:
   [[INTERVIEW_COMPLETE]]
   인터뷰가 끝나기 전에는 절대 이 토큰을 사용하지 마세요.
7. 다음 항목에 대해서는 절대 질문하지 마세요: 나이, 성별, 종교, 정치 성향, 건강,
   가족 관계, 결혼 여부, 임신, 장애, 출신/국적, 출신 학교의 명문 여부,
   기타 법적으로 보호되는 민감한 개인정보. 지원자가 자발적으로 언급해도
   평가에 반영하지 마세요.
8. 항상 존중하는 태도로 격려하며 진행하세요. 학습용 연습이라는 점을 기억하세요.
"""

SYSTEM_PROMPT_EVALUATION = f"""
당신은 학교 프로젝트용 모의 면접을 평가하는 시스템입니다.
다음 JSON 스키마에 맞는 JSON 객체만 출력하세요. 마크다운 코드펜스나 다른 설명은 절대 포함하지 마세요.
요약(summary), 강점(strengths), 우려(concerns), 추천 다음 단계(recommended_next_step),
채용 의견(hiring_opinion), 채용 추천 이유(hiring_recommendation_reason)는
모두 한국어로 작성하세요 (hiring_opinion은 "추천"/"보류"/"비추천" 중 하나).
evidence_quotes는 지원자의 실제 한국어 발언을 짧게 인용하세요.
지원자의 학력, 경력, 학점 등 제공된 배경 정보도 평가에 참고하세요.

루브릭 (각 항목 1~5점, 정수):
- culture_fit: {RUBRIC['culture_fit']}
- customer_response: {RUBRIC['customer_response']}
- ownership: {RUBRIC['ownership']}
- communication: {RUBRIC['communication']}
- learning_agility: {RUBRIC['learning_agility']}

JSON 스키마:
{{
  "scores": {{
    "culture_fit": <1~5 정수>,
    "customer_response": <1~5 정수>,
    "ownership": <1~5 정수>,
    "communication": <1~5 정수>,
    "learning_agility": <1~5 정수>
  }},
  "fit_level": "strong_match" | "possible_match" | "needs_human_review" | "weak_match",
  "summary": "<2~4문장의 중립적 요약>",
  "strengths": ["..."],
  "concerns": ["..."],
  "evidence_quotes": ["지원자의 짧은 직접 인용"],
  "recommended_next_step": "<채용 담당자에게 줄 짧은 제안>",
  "hiring_opinion": "추천" | "보류" | "비추천",
  "hiring_recommendation_reason": "<채용 의견 판단 이유를 2~3문장으로 작성>"
}}

fit_level 판정 가이드:
- strong_match: 평균 점수 >= 4.2 이고 모든 항목이 3점 이상
- possible_match: 평균 점수 >= 3.4
- weak_match: 평균 점수 < 2.5
- needs_human_review: 그 외, 또는 근거가 부족하거나 혼재된 경우

hiring_opinion 판정 가이드:
- 추천: fit_level이 strong_match 또는 possible_match이고 중대한 우려사항이 없을 때
- 보류: needs_human_review이거나 판단이 어려울 때
- 비추천: fit_level이 weak_match이거나 중대한 우려사항이 있을 때

자동 합격/불합격을 추천하지 마세요. 항상 사람 검토를 위한 제안으로 작성하세요.
민감한 개인정보는 무시하세요.
"""


# ---------------------------------------------------------------------------
# LLM helpers (OpenAI by default, easy to swap)
# ---------------------------------------------------------------------------

def llm_chat(messages: list[dict], temperature: float = 0.4) -> str:
    """Send a chat completion request and return the assistant text.

    Returns canned dummy text when DUMMY_MODE is on so the UI still works.
    """
    if DUMMY_MODE:
        return _dummy_interviewer_reply(messages)

    resp = _openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def llm_json(messages: list[dict], temperature: float = 0.2) -> dict:
    """Ask the LLM for a JSON object and parse it. Falls back to dummy JSON."""
    if DUMMY_MODE:
        return _dummy_evaluation_json()

    resp = _openai_client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    text = resp.choices[0].message.content or "{}"
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Last-ditch: try to extract a JSON object substring.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


# ---------------------------------------------------------------------------
# Dummy mode (so the demo works without an API key)
# ---------------------------------------------------------------------------

DUMMY_QUESTIONS = [
    "안녕하세요! 모의 면접에 참여해 주셔서 감사합니다. 먼저 간단한 자기소개와 함께, 고객을 응대하는 직무에 관심을 갖게 된 계기를 말씀해 주시겠어요?",
    "화가 난 고객을 응대했던 경험이 있다면 들려주세요. 어떤 상황이었고, 어떻게 대응하셨으며, 결과는 어땠나요?",
    "본인의 담당 업무가 아니었지만 직접 책임지고 해결했던 경험이 있다면 구체적으로 말씀해 주세요.",
    "받아들이기 어려웠던 피드백을 받은 경험이 있나요? 어떻게 반응했고, 이후 어떤 점이 달라졌나요?",
    "복잡한 내용을 잘 모르는 사람에게 설명해야 했던 상황이 있다면, 어떻게 풀어 설명하셨나요?",
    "최근 몇 달 사이에 새로 배운 것이 있다면 무엇이고, 어떤 방식으로 학습하셨나요?",
    "마지막 질문입니다. 본인이 가장 잘 일할 수 있는 팀 문화는 어떤 모습인가요?",
]


def _dummy_interviewer_reply(messages: list[dict]) -> str:
    """사용자 답변 수에 따라 다음 데모 질문을 선택."""
    user_turns = sum(1 for m in messages if m["role"] == "user")
    if user_turns >= MAX_ANSWERS:
        return "오늘 시간 내주셔서 정말 감사합니다. 준비된 질문은 여기까지입니다.\n[[INTERVIEW_COMPLETE]]"
    idx = min(user_turns, len(DUMMY_QUESTIONS) - 1)
    return DUMMY_QUESTIONS[idx]


def _dummy_evaluation_json() -> dict:
    return {
        "scores": {
            "culture_fit": 4,
            "customer_response": 4,
            "ownership": 3,
            "communication": 4,
            "learning_agility": 4,
        },
        "fit_level": "possible_match",
        "summary": (
            "데모 모드 평가입니다. 지원자는 고객 공감 능력과 명확한 의사소통 역량을 보여주었으며, "
            "주인의식 측면에서는 보통 수준의 근거가 확인되었습니다. 실제 LLM 호출 없이 생성된 "
            "예시 결과입니다."
        ),
        "strengths": ["명확한 의사소통", "고객 공감 능력", "학습에 대한 호기심"],
        "concerns": ["모호한 상황에서의 주인의식 근거가 다소 부족함"],
        "evidence_quotes": ["(데모 모드 - 실제 인용은 수집되지 않았습니다)"],
        "recommended_next_step": "주인의식과 책임감을 중점적으로 확인하는 사람 면접을 추천합니다.",
        "hiring_opinion": "보류",
        "hiring_recommendation_reason": "데모 모드 평가입니다. 실제 면접 후 채용 담당자의 상세 검토를 권장합니다.",
    }


# ---------------------------------------------------------------------------
# Evaluation logic
# ---------------------------------------------------------------------------

def transcript_text(messages: list[dict]) -> str:
    """대화 기록을 일반 텍스트 형식으로 변환."""
    lines = []
    for m in messages:
        role = m["role"]
        if role == "system":
            continue
        speaker = "면접관" if role == "assistant" else "지원자"
        lines.append(f"{speaker}: {m['content']}")
    return "\n".join(lines)


def build_final_payload(
    raw_eval: dict,
    candidate_name: str,
    candidate_email: str,
    position: str,
    gpa: str,
    degree: str,
    experience: str,
    transcript: str,
) -> dict:
    """평가 결과 + 지원자 정보를 최종 dict로 조립 (pipeline / GAS 전송용)."""
    scores = raw_eval.get("scores", {}) or {}

    def clamp(v) -> int:
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            n = 3
        return max(1, min(5, n))

    cleaned_scores = {
        "culture_fit": clamp(scores.get("culture_fit")),
        "customer_response": clamp(scores.get("customer_response")),
        "ownership": clamp(scores.get("ownership")),
        "communication": clamp(scores.get("communication")),
        "learning_agility": clamp(scores.get("learning_agility")),
    }
    overall = round(sum(cleaned_scores.values()) / len(cleaned_scores), 2)
    cleaned_scores["overall"] = overall

    fit_level = raw_eval.get("fit_level", "needs_human_review")
    if fit_level not in ALLOWED_FIT_LEVELS:
        fit_level = "needs_human_review"

    return {
        "project_notice": PROJECT_NOTICE,
        "candidate_name": candidate_name or "익명 지원자",
        "candidate_email": candidate_email or "",
        "position": position or "",
        "degree": degree or "",
        "gpa": gpa or "",
        "experience": experience or "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scores": cleaned_scores,
        "fit_level": fit_level,
        "hiring_opinion": raw_eval.get("hiring_opinion", ""),
        "hiring_recommendation_reason": raw_eval.get("hiring_recommendation_reason", ""),
        "summary": raw_eval.get("summary", ""),
        "strengths": list(raw_eval.get("strengths") or []),
        "concerns": list(raw_eval.get("concerns") or []),
        "evidence_quotes": list(raw_eval.get("evidence_quotes") or []),
        "recommended_next_step": raw_eval.get("recommended_next_step", ""),
        "transcript": transcript,
    }


def _llm_text(prompt: str) -> str:
    """파이프라인용 단발 LLM 호출 (2차 면접 질문 생성 등)."""
    return llm_chat([{"role": "user", "content": prompt}], temperature=0.3)


def execute_pipeline(payload: dict, *, skip_interview_save: bool = False) -> PipelineResult:
    """면접 결과 저장 + outbox 큐잉 (Zapier는 outbox 시트 New Row로 앱 연결).

    skip_interview_save=True면 interviews 행은 다시 쓰지 않고 outbox만 재생성한다.
    재전송 경로에서도 llm_fn을 전달해야 보류 분기의 2차 질문이 유실되지 않는다.
    """
    cfg = load_pipeline_config()

    if DUMMY_MODE:
        def llm_fn(_prompt: str) -> str:
            return (
                "1. [데모] 고객 불만 상황에서 본인의 역할을 STAR 형식으로 설명해 주세요.\n"
                "2. [데모] 팀 내 갈등을 조율했던 경험이 있다면 말씀해 주세요.\n"
                "3. [데모] 새로운 업무를 빠르게 학습했던 사례를 알려 주세요."
            )
    else:
        llm_fn = _llm_text

    return run_pipeline(
        payload,
        cfg["webhook_url"],
        admin_email=cfg["admin_email"],
        admin_slack=cfg["admin_slack"],
        notion_database=cfg["notion_database"],
        llm_fn=llm_fn,
        skip_interview_save=skip_interview_save,
    )


# ---------------------------------------------------------------------------
# Recruiter config helper (read-only from app.py)
# ---------------------------------------------------------------------------

def load_recruiter_config() -> dict:
    """채용 담당자 설정 JSON을 로드합니다.
    파일이 없으면 기본 포지션으로 파일을 자동 생성합니다.
    """
    if os.path.exists(RECRUITER_CONFIG_PATH):
        try:
            with open(RECRUITER_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    # 파일 없음 → 기본 포지션으로 초기 파일 생성
    default = {"positions": DEFAULT_POSITIONS, "general_criteria": "", "updated_at": ""}
    try:
        with open(RECRUITER_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return default


# ---------------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------------

_APP_CSS = """
<style>
.block-container { padding-top: 1.2rem; max-width: 920px; }
div[data-testid="stForm"] {
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,0.2);
    border-radius: 18px;
    padding: 28px 24px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
div[data-testid="stChatMessage"] {
    border-radius: 16px;
    padding: 12px 16px;
    margin-bottom: 10px;
    border: 1px solid rgba(128,128,128,0.15);
}
button[kind="primaryFormSubmit"], button[kind="primary"] {
    border-radius: 12px;
    font-weight: 600;
}
.hc-hero {
    background: linear-gradient(135deg, #0d9488 0%, #14b8a6 50%, #5eead4 100%);
    padding: 28px 32px;
    border-radius: 20px;
    margin-bottom: 20px;
    color: #fff;
}
.hc-hero h1 { margin: 0; font-size: 1.65rem; font-weight: 700; }
.hc-hero p { margin: 8px 0 0; opacity: 0.92; font-size: 0.95rem; }
.hc-steps {
    display: flex;
    gap: 8px;
    margin: 16px 0 20px;
    flex-wrap: wrap;
}
.hc-step {
    flex: 1;
    min-width: 100px;
    text-align: center;
    padding: 10px 8px;
    border-radius: 12px;
    font-size: 0.82rem;
    font-weight: 600;
    background: var(--secondary-background-color);
    border: 2px solid rgba(128,128,128,0.2);
    color: var(--text-color);
    opacity: 0.55;
}
.hc-step.active {
    border-color: #14b8a6;
    background: rgba(20,184,166,0.12);
    opacity: 1;
}
.hc-step.done { opacity: 0.75; border-color: #99f6e4; }
.hc-card {
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,0.18);
    border-radius: 16px;
    padding: 20px 22px;
    margin-bottom: 16px;
}
.hc-tip {
    background: rgba(20,184,166,0.08);
    border-left: 4px solid #14b8a6;
    padding: 14px 18px;
    border-radius: 0 12px 12px 0;
    margin-bottom: 16px;
    font-size: 0.92rem;
    line-height: 1.55;
}
.hc-profile {
    background: var(--secondary-background-color);
    border-radius: 14px;
    padding: 14px 16px;
    margin-bottom: 12px;
    border: 1px solid rgba(128,128,128,0.15);
}
.hc-profile dt { font-size: 0.75rem; opacity: 0.65; margin-top: 8px; }
.hc-profile dd { margin: 2px 0 0; font-weight: 600; font-size: 0.9rem; }
.hc-result-hero {
    text-align: center;
    padding: 32px 24px;
    border-radius: 20px;
    margin-bottom: 20px;
    background: var(--secondary-background-color);
    border: 1px solid rgba(128,128,128,0.15);
}
.hc-opinion {
    display: inline-block;
    font-size: 1.5rem;
    font-weight: 700;
    padding: 8px 24px;
    border-radius: 999px;
    margin: 12px 0;
}
.hc-opinion.rec { background: #d1fae5; color: #065f46; }
.hc-opinion.hold { background: #fef3c7; color: #92400e; }
.hc-opinion.rej { background: #fee2e2; color: #991b1b; }
div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-of-type(2) {
    position: sticky;
    top: 4.5rem;
    align-self: flex-start;
    max-height: calc(100vh - 6rem);
    overflow-y: auto;
}
</style>
"""


def _render_steps(current: int) -> None:
    """current: 1=정보입력, 2=면접, 3=결과"""
    labels = ["① 정보 입력", "② AI 면접", "③ 결과 확인"]
    parts = []
    for i, label in enumerate(labels, start=1):
        cls = "hc-step"
        if i == current:
            cls += " active"
        elif i < current:
            cls += " done"
        parts.append(f'<div class="{cls}">{label}</div>')
    st.markdown(f'<div class="hc-steps">{"".join(parts)}</div>', unsafe_allow_html=True)


def _opinion_class(opinion: str) -> str:
    return {"추천": "rec", "보류": "hold", "비추천": "rej"}.get(opinion, "hold")


st.set_page_config(
    page_title="HireCopilot — AI 모의 면접",
    page_icon="🎓",
    layout="centered",
)

st.markdown(_APP_CSS, unsafe_allow_html=True)

st.markdown(
    """
    <div class="hc-hero">
      <h1>🎓 HireCopilot</h1>
      <p>AI 면접관과 편하게 대화하는 모의 면접 · 약 10~15분 소요</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if DUMMY_MODE:
    st.caption("💡 데모 모드 — API 키 없이 미리 준비된 질문으로 체험합니다.")


# --- Session state ---
# 면접 흐름에 쓰는 키만 명시적으로 관리 (전체 session_state 삭제는 위젯 상태 꼬임 유발)
_INTERVIEW_SESSION_KEYS = (
    "interview_done",
    "final_payload",
    "pipeline_result",
    "pipeline_error",
    "admin_record_id",
    "greeted",
    "onboarding_done",
    "messages",
    "running_eval",
    "celebrated",
    "confirm_restart",
    "tip_dismissed",
    "candidate_name",
    "candidate_email",
    "degree",
    "experience",
    "gpa",
    "position",
)


def reset_interview_session() -> None:
    """면접 재시작 시 인터뷰 관련 상태만 초기화."""
    for key in _INTERVIEW_SESSION_KEYS:
        st.session_state.pop(key, None)


def _init_state():
    # messages는 온보딩 완료 후 포지션 확정 시점에 초기화 (아래 온보딩 블록 이후 참고)
    st.session_state.setdefault("interview_done", False)
    st.session_state.setdefault("final_payload", None)
    st.session_state.setdefault("pipeline_result", None)
    st.session_state.setdefault("pipeline_error", None)
    st.session_state.setdefault("admin_record_id", None)
    st.session_state.setdefault("greeted", False)
    st.session_state.setdefault("onboarding_done", False)
    st.session_state.setdefault("dev_mode", False)
    st.session_state.setdefault("dev_mode_pending", False)
    st.session_state.setdefault("running_eval", None)
    st.session_state.setdefault("celebrated", False)
    st.session_state.setdefault("confirm_restart", False)


_init_state()


# --- 온보딩: 면접 시작 전 지원자 정보 입력 ---
if not st.session_state.onboarding_done:
    _render_steps(1)
    st.markdown(
        '<div class="hc-tip">'
        "<strong>면접 전 알아두세요</strong><br>"
        "• 한국어 존댓말로 답변해 주세요<br>"
        "• 질문은 약 6~8개, 구체적인 경험을 말씀해 주시면 좋아요<br>"
        "• 결과는 참고용이며, 최종 결정은 채용 담당자가 합니다"
        "</div>",
        unsafe_allow_html=True,
    )
    _gpa_required = load_pipeline_config()["require_gpa"]
    _ob_rcfg = load_recruiter_config()
    _ob_positions = [p["name"] for p in _ob_rcfg.get("positions", [])]
    if not _ob_positions:
        st.warning("지원 가능한 포지션이 없습니다. 채용 담당자에게 문의해 주세요.")
    with st.form("onboarding_form"):
        st.markdown("**기본 정보**")
        col_a, col_b = st.columns(2)
        with col_a:
            ob_name = st.text_input("이름", placeholder="홍길동")
            ob_degree = st.selectbox("최종 학력", options=DEGREE_OPTIONS)
        with col_b:
            ob_email = st.text_input("이메일", placeholder="name@email.com")
            ob_experience = st.selectbox("경력", options=EXPERIENCE_OPTIONS)
        ob_gpa = st.text_input(
            "학점" + (" (필수)" if _gpa_required else " (선택)"),
            placeholder="예: 3.8",
        )
        st.markdown("**지원 포지션**")
        ob_position = st.selectbox(
            "어떤 포지션에 지원하시나요?",
            options=_ob_positions or ["(포지션 없음)"],
            disabled=not _ob_positions,
            label_visibility="collapsed",
        )
        _selected_criteria = next(
            (p.get("criteria", "") for p in _ob_rcfg.get("positions", []) if p.get("name") == ob_position),
            "",
        )
        if _selected_criteria:
            st.caption(f"📌 이 포지션에서 중요하게 보는 점: {_selected_criteria}")
        submitted = st.form_submit_button(
            "면접 시작하기",
            use_container_width=True,
            type="primary",
            disabled=not _ob_positions,
        )
        if submitted:
            errors = []
            if not ob_name.strip():
                errors.append("이름을 입력해 주세요.")
            if not ob_email.strip() or "@" not in ob_email:
                errors.append("올바른 이메일을 입력해 주세요.")
            if _gpa_required and not ob_gpa.strip():
                errors.append("학점을 입력해 주세요.")
            if errors:
                for err in errors:
                    st.error(err)
            else:
                st.session_state["candidate_name"] = ob_name.strip()
                st.session_state["candidate_email"] = ob_email.strip()
                st.session_state["degree"] = ob_degree
                st.session_state["experience"] = ob_experience
                st.session_state["gpa"] = ob_gpa.strip()
                st.session_state["position"] = ob_position
                st.session_state.onboarding_done = True
                st.rerun()
    st.stop()


def _user_answer_count() -> int:
    return sum(1 for m in st.session_state.get("messages", []) if m["role"] == "user")


# --- 온보딩 완료 후: 채용 담당자 설정 반영한 면접 메시지 초기화 ---
if "messages" not in st.session_state:
    _rcfg = load_recruiter_config()
    _prompt = _build_interview_prompt(
        candidate_position=st.session_state.get("position", ""),
        recruiter_config=_rcfg,
    )
    st.session_state.messages = [{"role": "system", "content": _prompt}]


# --- 사이드바 ---
with st.sidebar:
    if st.session_state.final_payload:
        _render_steps(3)
    elif st.session_state.interview_done:
        _render_steps(3)
    else:
        _render_steps(2)

    gpa_line = (
        f'<dt>학점</dt><dd>{st.session_state.get("gpa")}</dd>'
        if st.session_state.get("gpa")
        else ""
    )
    st.markdown(
        f"""
        <div class="hc-profile">
          <dt>이름</dt><dd>{st.session_state.get("candidate_name", "-")}</dd>
          <dt>포지션</dt><dd>{st.session_state.get("position", "-")}</dd>
          <dt>학력 · 경력</dt>
          <dd>{st.session_state.get("degree", "-")} · {st.session_state.get("experience", "-")}</dd>
          {gpa_line}
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not st.session_state.interview_done:
        answered = _user_answer_count()
        pct = min(answered / MAX_ANSWERS, 1.0)
        st.progress(pct, text=f"답변 {answered} / {MAX_ANSWERS}")
    elif st.session_state.final_payload:
        st.success("✅ 면접 완료")

    st.divider()
    if not st.session_state.confirm_restart:
        if st.button("🔄 처음부터 다시", use_container_width=True):
            st.session_state.confirm_restart = True
            st.rerun()
    else:
        st.warning("모든 내용이 삭제됩니다.")
        if st.button("네, 다시 시작", use_container_width=True, type="primary"):
            reset_interview_session()
            st.rerun()
        if st.button("취소", use_container_width=True):
            st.session_state.confirm_restart = False
            st.rerun()

    with st.expander("고급 설정 (개발자용)"):
        toggle_val = st.toggle("실시간 평가 패널", value=st.session_state.dev_mode)
        if toggle_val and not st.session_state.dev_mode:
            st.session_state.dev_mode_pending = True
        elif not toggle_val:
            st.session_state.dev_mode = False
            st.session_state.dev_mode_pending = False
        if st.session_state.dev_mode_pending and not st.session_state.dev_mode:
            pw_input = st.text_input("암호", type="password", key="dev_pw_input")
            if st.button("확인", key="dev_pw_confirm"):
                if (DEV_TOGGLE_PASSWORD and pw_input == DEV_TOGGLE_PASSWORD) or not DEV_TOGGLE_PASSWORD:
                    st.session_state.dev_mode = True
                    st.session_state.dev_mode_pending = False
                    st.rerun()
                else:
                    st.error("암호가 틀렸습니다.")
        if st.session_state.dev_mode and not st.session_state.interview_done:
            if st.button("면접 즉시 종료"):
                st.session_state.interview_done = True
                st.rerun()
        if st.session_state.dev_mode:
            st.caption(f"모델: {OPENAI_MODEL} · {'데모' if DUMMY_MODE else 'OpenAI'}")


# --- 첫 인사 메시지 ---
if not st.session_state.greeted:
    with st.spinner("면접을 준비하는 중입니다..."):
        first_msg = llm_chat(st.session_state.messages)
    st.session_state.messages.append({"role": "assistant", "content": first_msg})
    st.session_state.greeted = True


# ---------------------------------------------------------------------------
# 실시간 평가 (개발자 모드용)
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_RUNNING_EVAL = f"""
당신은 진행 중인 면접을 실시간으로 분석하는 평가 보조 시스템입니다.
지원자가 1회 이상 답변했다면, 다섯 항목 모두에 대해 반드시 1~5 정수 점수를 매기세요.
null 은 절대 반환하지 마세요. 근거가 부족하면 보수적으로 낮은 점수(1~2)부터 시작하고,
대화가 진행되면서 점수를 갱신하세요. 답변이 없는 첫 호출에서만 모든 점수를 1로 두세요.

summary 는 지금까지의 대화 전체를 1~3문장으로 한국어로 자연스럽게 요약하세요.
- 지원자가 어떤 직무/배경에 관심을 가지고 있는지
- 어떤 경험/사례를 언급했는지
- 어떤 강점/약점이 드러났는지
빈 문자열로 두지 마세요. 답변이 적다면 "지원자는 아직 ~ 만 답변했습니다" 식으로라도 작성.

출력은 반드시 아래 JSON 스키마만 따르세요. 마크다운 펜스/설명 금지.

루브릭:
- culture_fit: {RUBRIC['culture_fit']}
- customer_response: {RUBRIC['customer_response']}
- ownership: {RUBRIC['ownership']}
- communication: {RUBRIC['communication']}
- learning_agility: {RUBRIC['learning_agility']}

스키마:
{{
  "scores": {{
    "culture_fit": <1~5 정수>,
    "customer_response": <1~5 정수>,
    "ownership": <1~5 정수>,
    "communication": <1~5 정수>,
    "learning_agility": <1~5 정수>
  }},
  "summary": "<지금까지의 대화 요약 1~3문장 한국어>"
}}
"""


def update_running_eval():
    """현재 대화록을 바탕으로 실시간 평가를 갱신해 session_state에 저장."""
    transcript = transcript_text(st.session_state.messages)
    if not transcript.strip():
        return

    if DUMMY_MODE:
        # 데모 모드: 답변 수에 따라 모든 점수가 점진적으로 올라가는 모습 시연
        n = _user_answer_count()
        keys = ["communication", "customer_response", "ownership", "culture_fit", "learning_agility"]
        # 모든 항목 1점에서 시작, 답변마다 점진 증가 (최대 5)
        base = min(1 + n // 2, 5)
        scores = {k: max(1, min(5, base + (i % 2))) for i, k in enumerate(keys)}
        st.session_state.running_eval = {
            "scores": scores,
            "summary": (
                f"데모 모드 요약: 지원자가 지금까지 {n}개의 답변을 했습니다. "
                "대화가 진행될수록 점수가 갱신됩니다."
            ),
            "_error": None,
        }
        return

    try:
        result = llm_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT_RUNNING_EVAL},
                {"role": "user", "content": f"현재까지의 대화록:\n{transcript}"},
            ],
            temperature=0.2,
        )
        if isinstance(result, dict):
            result["_error"] = None
        st.session_state.running_eval = result
    except Exception as e:
        # 에러를 패널에 표시할 수 있도록 저장 (조용히 삼키지 않음)
        prev = st.session_state.get("running_eval") or {}
        prev["_error"] = f"{type(e).__name__}: {e}"
        st.session_state.running_eval = prev


def render_dev_panel():
    """우측 개발자 패널 - 실시간 점수/요약/체크 표시."""
    is_done = st.session_state.interview_done
    final = st.session_state.final_payload  # 면접 종료 후 최종 평가 (있으면 이걸 우선 사용)

    st.subheader("실시간 평가")
    st.caption("면접이 끝나면 최종 결과로 바뀝니다.")

    # 표시할 데이터: 종료 후엔 최종 payload, 진행 중엔 running_eval
    if final:
        scores = final.get("scores") or {}
        summary = final.get("summary", "")
        error = None
    else:
        eval_data = st.session_state.running_eval or {}
        scores = (eval_data.get("scores") or {}) if isinstance(eval_data, dict) else {}
        summary = eval_data.get("summary", "") if isinstance(eval_data, dict) else ""
        error = eval_data.get("_error") if isinstance(eval_data, dict) else None

    if error:
        st.error(f"⚠️ 실시간 평가 LLM 호출 실패: {error}")

    rubric_labels = {
        "culture_fit": "문화 적합도",
        "customer_response": "고객 응대",
        "ownership": "주인의식",
        "communication": "커뮤니케이션",
        "learning_agility": "학습 민첩성",
    }

    st.markdown("**항목별 점수**")
    # 슬라이드 바 HTML 렌더링.
    # 주의: Streamlit markdown은 줄 시작에 4칸 이상 공백이 있으면 코드블럭으로 인식하므로
    # HTML은 반드시 들여쓰기 없이 한 줄로 작성해야 한다.
    bar_html = '<div style="margin-top:6px;">'
    for key, label in rubric_labels.items():
        val = scores.get(key)
        check = "⏳" if val is None else "✅"
        score_text = "-" if val is None else f"{val} / 5"
        ratio = 0.0 if val is None else max(0.0, min(1.0, val / 5))
        if val is None:
            color = "#cccccc"
        elif val <= 2:
            color = "#e74c3c"
        elif val == 3:
            color = "#f39c12"
        else:
            color = "#27ae60"
        bar_html += (
            f'<div style="margin-bottom:14px;">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;font-size:0.9rem;">'
            f'<span>{check} <strong>{label}</strong></span>'
            f'<span style="font-weight:600;">{score_text}</span>'
            f'</div>'
            f'<div style="background:#eaeaea;border-radius:8px;height:10px;width:100%;">'
            f'<div style="width:{ratio*100:.0f}%;background:{color};height:100%;border-radius:8px;transition:width 0.4s ease;"></div>'
            f'</div>'
            f'</div>'
        )
    bar_html += "</div>"
    st.markdown(bar_html, unsafe_allow_html=True)

    if "overall" in scores:
        st.markdown(f"**🏁 종합 점수: {scores['overall']} / 5**")
    if final and final.get("fit_level"):
        st.markdown(f"**🎯 적합도: `{final['fit_level']}`**")

    st.divider()
    st.markdown("**요약**")
    if summary:
        st.success("✅ 요약 생성됨")
        st.write(summary)
    else:
        st.info("⏳ 아직 요약을 생성할 만큼의 근거가 부족합니다.")

    if final:
        st.divider()
        if final.get("strengths"):
            st.markdown("**강점**")
            for s in final["strengths"]:
                st.markdown(f"- {s}")
        if final.get("concerns"):
            st.markdown("**우려사항**")
            for s in final["concerns"]:
                st.markdown(f"- {s}")
        if final.get("hiring_opinion"):
            opinion_color = {"\ucd94\ucc9c": "🟢", "\ubcf4\ub958": "🟡", "\ube44\ucd94\ucc9c": "🔴"}.get(final["hiring_opinion"], "\u26aa")
            st.markdown(f"**{opinion_color} 채용 의견: `{final['hiring_opinion']}`**")
        if final.get("hiring_recommendation_reason"):
            st.markdown("**채용 판단 이유**")
            st.write(final["hiring_recommendation_reason"])
        if final.get("recommended_next_step"):
            st.markdown("**추천 다음 단계**")
            st.write(final["recommended_next_step"])

    st.divider()
    st.markdown("**진행 현황**")
    answered = _user_answer_count()
    st.progress(min(answered / MAX_ANSWERS, 1.0))
    st.caption(f"지원자 답변 {answered} / 최대 {MAX_ANSWERS}")

    with st.expander("대화록 / 디버그"):
        if st.button("평가 강제 갱신", use_container_width=True):
            with st.spinner("갱신 중..."):
                update_running_eval()
            st.rerun()
        raw = st.session_state.get("running_eval")
        if raw is not None:
            st.json(raw)
        st.code(transcript_text(st.session_state.messages) or "(아직 없음)", language="text")


# ---------------------------------------------------------------------------
# 분할 레이아웃: 좌측 채팅 / 우측 개발자 패널 (개발자 모드일 때 항상 표시)
# ---------------------------------------------------------------------------
if st.session_state.dev_mode:
    st.markdown('<div style="max-width:1100px;margin:0 auto;">', unsafe_allow_html=True)
    chat_col, dev_col = st.columns([3, 2], gap="large")
else:
    dev_col = None
    chat_col = st.container()


with chat_col:
    if not st.session_state.interview_done and not st.session_state.get("tip_dismissed"):
        st.markdown(
            '<div class="hc-tip">'
            "💡 <strong>답변 팁</strong> — 상황 → 내가 한 일 → 결과 순으로 말하면 좋아요. "
            "아래 입력창에 답변을 적고 Enter를 누르세요."
            "</div>",
            unsafe_allow_html=True,
        )
        if st.button("알겠어요", key="dismiss_tip"):
            st.session_state.tip_dismissed = True
            st.rerun()
    # --- 대화 기록 렌더링 (system 메시지는 건너뜀) ---
    for m in st.session_state.messages:
        if m["role"] == "system":
            continue
        visible = m["content"].replace("[[INTERVIEW_COMPLETE]]", "").strip()
        if not visible:
            continue
        if m["role"] == "assistant":
            with st.chat_message("assistant", avatar="🧑‍💼"):
                st.markdown(visible)
        else:
            with st.chat_message("user", avatar="🙋"):
                st.markdown(visible)

# --- 채팅 입력 (st.chat_input은 컬럼 밖에 있어야 페이지 하단에 고정됨) ---
if not st.session_state.interview_done:
    user_input = st.chat_input("여기에 답변을 입력하고 Enter를 누르세요")
    if user_input:
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.spinner("면접관이 생각 중입니다..."):
            reply = llm_chat(st.session_state.messages)

        # 모델이 종료 토큰을 출력하지 않더라도, 최대 답변 수에 도달하면 강제 종료.
        if _user_answer_count() >= MAX_ANSWERS and "[[INTERVIEW_COMPLETE]]" not in reply:
            reply = (
                reply.rstrip()
                + "\n\n오늘 시간 내주셔서 감사합니다. 준비된 질문은 여기까지입니다.\n[[INTERVIEW_COMPLETE]]"
            )

        st.session_state.messages.append({"role": "assistant", "content": reply})

        if "[[INTERVIEW_COMPLETE]]" in reply:
            st.session_state.interview_done = True

        # 개발자 모드면 매 답변마다 실시간 평가 갱신 (면접이 끝나도 마지막 답변까지 반영)
        if st.session_state.dev_mode:
            with st.spinner("실시간 평가 갱신 중..."):
                update_running_eval()

        st.rerun()


# --- 개발자 패널 렌더링 ---
if dev_col is not None:
    with dev_col:
        render_dev_panel()


# --- 면접 종료 후: 평가 생성 및 파이프라인 실행 ---
if st.session_state.interview_done and st.session_state.final_payload is None:
    with st.status("면접 결과를 처리하는 중...", expanded=True) as status:
        st.write("1/3 — 대화록 정리 및 AI 평가 생성")
        transcript = transcript_text(st.session_state.messages)
        _eval_rcfg = load_recruiter_config()
        _eval_pos = st.session_state.get("position", "")
        _role_criteria = next(
            (p.get("criteria", "") for p in _eval_rcfg.get("positions", []) if p.get("name") == _eval_pos),
            "",
        )
        _general_criteria = _eval_rcfg.get("general_criteria", "")
        eval_messages = [
            {"role": "system", "content": SYSTEM_PROMPT_EVALUATION},
            {
                "role": "user",
                "content": (
                    f"지원자 이름: {st.session_state.get('candidate_name') or '미입력'}\n"
                    f"지원 포지션: {_eval_pos or '미입력'}\n"
                    f"최종 학력: {st.session_state.get('degree') or '미입력'}\n"
                    f"경력: {st.session_state.get('experience') or '미입력'}\n"
                    f"학점: {st.session_state.get('gpa') or '미입력'}\n"
                    + (f"\n해당 포지션 채용 중점 기준: {_role_criteria}\n" if _role_criteria else "")
                    + (f"공통 채용 중점 기준: {_general_criteria}\n" if _general_criteria else "")
                    + f"\n대화록:\n{transcript}\n\n"
                    + "위 대화록을 바탕으로 JSON 평가를 생성하세요."
                ),
            },
        ]
        try:
            raw_eval = llm_json(eval_messages)
        except Exception as e:
            st.warning(f"평가 LLM 호출 실패 — 데모 평가로 대체: {e}")
            raw_eval = _dummy_evaluation_json()

        st.write("2/3 — 최종 평가 JSON 조립")
        payload = build_final_payload(
            raw_eval=raw_eval,
            candidate_name=st.session_state.get("candidate_name", ""),
            candidate_email=st.session_state.get("candidate_email", ""),
            position=st.session_state.get("position", ""),
            gpa=st.session_state.get("gpa", ""),
            degree=st.session_state.get("degree", ""),
            experience=st.session_state.get("experience", ""),
            transcript=transcript,
        )
        st.session_state.final_payload = payload

        st.write("3/3 — 시트 저장 및 outbox 큐잉")
        try:
            st.session_state.pipeline_result = execute_pipeline(payload)
            st.session_state.pipeline_error = None
        except Exception as e:
            st.session_state.pipeline_result = None
            st.session_state.pipeline_error = f"{type(e).__name__}: {e}"
        try:
            record = save_interview_record(payload, st.session_state.pipeline_result)
            st.session_state.admin_record_id = record.get("record_id")
        except OSError as e:
            st.warning(f"관리자 콘솔 기록 저장에 실패: {e}")
        status.update(label="처리 완료", state="complete", expanded=False)
    st.rerun()


_OUTBOX_LABELS = {
    "outbox_email": "이메일 발송",
    "outbox_slack": "Slack 알림",
    "outbox_notion": "Notion 등록",
    "outbox_docs": "면접 질문 문서",
    "outbox_zoom": "Zoom 미팅",
    "outbox_scheduled": "합격 메일 예약",
    "pipeline_log": "처리 기록",
}


def _render_pipeline_status(result: PipelineResult) -> None:
    ok, msg = result.interview_saved
    if ok:
        st.success("면접 기록이 저장되었습니다.")
    else:
        st.warning(f"면접 기록 저장 실패: {msg}")

    if not result.screening_passed:
        st.info(f"자격 요건 미충족으로 후속 알림이 생략되었습니다. ({result.screening_reason})")
        return

    for target, action_ok, action_msg in result.action_results:
        if target == "pipeline_log":
            continue
        label = _OUTBOX_LABELS.get(target, target)
        if action_ok:
            st.write(f"✅ {label}")
        else:
            st.write(f"⚠️ {label} — {action_msg}")

    if result.has_outbox_actions and not result.outbox_actions_ok:
        if st.button("실패한 항목 다시 보내기", key="retry_outbox"):
            st.session_state.pipeline_result = retry_failed_outbox(result)
            st.rerun()


# --- 결과 표시 ---
if st.session_state.final_payload is not None:
    if not st.session_state.get("celebrated"):
        st.balloons()
        st.session_state.celebrated = True

    final = st.session_state.final_payload
    scores = final.get("scores") or {}
    opinion = final.get("hiring_opinion", "")
    opinion_text = {"추천": "추천", "보류": "추가 검토 필요", "비추천": "아쉽게도 다음 단계 어려움"}.get(
        opinion, opinion or "—"
    )

    st.markdown(
        f"""
        <div class="hc-result-hero">
          <div style="font-size:2.5rem;">🎉</div>
          <h2 style="margin:8px 0 4px;">면접이 끝났어요!</h2>
          <p style="opacity:0.7;margin:0;">수고하셨습니다. 아래는 AI가 정리한 참고 결과입니다.</p>
          <div class="hc-opinion {_opinion_class(opinion)}">{opinion_text}</div>
          <p style="font-size:1.1rem;margin:0;">종합 점수 <strong>{scores.get('overall', '-')} / 5</strong></p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if final.get("summary"):
        st.markdown(f"**한 줄 요약** — {final['summary']}")

    rubric_labels = {
        "culture_fit": "문화 적합",
        "customer_response": "고객 응대",
        "ownership": "주인의식",
        "communication": "소통",
        "learning_agility": "학습력",
    }
    score_cols = st.columns(5)
    for col, (key, label) in zip(score_cols, rubric_labels.items()):
        col.metric(label, f"{scores.get(key, '-')}")

    col_s, col_c = st.columns(2)
    with col_s:
        if final.get("strengths"):
            st.markdown("**잘한 점**")
            for s in final["strengths"]:
                st.markdown(f"- {s}")
    with col_c:
        if final.get("concerns"):
            st.markdown("**보완하면 좋을 점**")
            for c in final["concerns"]:
                st.markdown(f"- {c}")

    st.caption("※ AI 평가는 참고용이며, 최종 결정은 채용 담당자가 합니다.")

    with st.expander("저장 및 알림 상태 (운영자용)"):
        if st.session_state.get("admin_record_id"):
            st.caption(f"관리자 콘솔 기록 ID: `{st.session_state.admin_record_id}`")
        if st.session_state.pipeline_result:
            _render_pipeline_status(st.session_state.pipeline_result)
        elif st.session_state.get("pipeline_error"):
            st.error(f"후속 처리 실패: {st.session_state.pipeline_error}")

            def _rerun_pipeline(skip_interview_save: bool) -> None:
                try:
                    st.session_state.pipeline_result = execute_pipeline(
                        st.session_state.final_payload,
                        skip_interview_save=skip_interview_save,
                    )
                    st.session_state.pipeline_error = None
                except Exception as e:
                    st.session_state.pipeline_result = None
                    st.session_state.pipeline_error = f"{type(e).__name__}: {e}"
                try:
                    save_interview_record(st.session_state.final_payload, st.session_state.pipeline_result)
                except OSError:
                    pass
                st.rerun()

            if st.button("다시 시도"):
                _rerun_pipeline(skip_interview_save=False)

    st.download_button(
        "결과 파일 다운로드 (JSON)",
        data=json.dumps(st.session_state.final_payload, indent=2, ensure_ascii=False),
        file_name="면접결과.json",
        mime="application/json",
        use_container_width=True,
    )
