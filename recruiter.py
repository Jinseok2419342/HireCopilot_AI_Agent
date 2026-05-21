"""
HireCopilot - 채용 담당자 설정 페이지

채용 담당자가 포지션별 AI 면접 기준을 설정하는 별개 Streamlit 앱입니다.
실행: streamlit run recruiter.py --server.port 8502
"""

import json
import os
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv

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
    # 파일 없음 → 기본 포지션으로 초기 파일 생성
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


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="HireCopilot - 채용 담당자 설정",
    page_icon="👔",
    layout="centered",
)
st.title("👔 채용 담당자 설정")
st.caption("채용할 포지션과 각 포지션별 AI 면접 중점 평가 기준을 입력하세요.")

# --- 인증 ---
if not st.session_state.get("recruiter_authenticated"):
    st.subheader("🔒 채용 담당자 인증")
    pw = st.text_input("암호", type="password", key="recruiter_login_pw")
    if st.button("로그인", key="recruiter_login_btn", use_container_width=True):
        if (RECRUITER_PASSWORD and pw == RECRUITER_PASSWORD) or not RECRUITER_PASSWORD:
            st.session_state.recruiter_authenticated = True
            st.rerun()
        else:
            st.error("암호가 올바르지 않습니다.")
    st.stop()

# --- 설정 로드 ---
config = load_recruiter_config()
if "recruiter_positions" not in st.session_state:
    st.session_state.recruiter_positions = list(config.get("positions", []))

# --- 포지션 관리 ---
st.subheader("📌 채용 포지션 관리")
st.caption("각 포지션에 대해 AI 면접관이 중점적으로 평가할 기준을 입력하세요.")

with st.expander("➕ 새 포지션 추가"):
    new_pos_name = st.text_input(
        "포지션 이름", key="new_pos_name_input",
        placeholder="예: IT 개발자, 마케팅 담당자",
    )
    new_pos_criteria = st.text_area(
        "중점 평가 기준", key="new_pos_criteria_input", height=100,
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
        with st.expander(f"📋 {pos['name']}", expanded=True):
            updated_name = st.text_input("포지션 이름", value=pos["name"], key=f"pos_name_{i}")
            updated_criteria = st.text_area(
                "중점 평가 기준", value=pos.get("criteria", ""),
                key=f"pos_criteria_{i}", height=120,
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
                if st.button("🗑️ 삭제", key=f"del_pos_{i}"):
                    st.session_state.recruiter_positions.pop(i)
                    st.rerun()
else:
    st.info("등록된 포지션이 없습니다. 위에서 포지션을 추가하세요.")

st.divider()

# --- 공통 기준 ---
st.subheader("📝 공통 채용 중점 사항")
general_criteria = st.text_area(
    "모든 포지션에 공통으로 적용될 채용 기준",
    value=config.get("general_criteria", ""), height=120,
    placeholder="예: 팀워크와 커뮤니케이션을 중시합니다. 자기 주도적 학습 능력을 가진 인재를 선호합니다.",
    key="general_criteria_input",
)

st.divider()

if st.button("💾 설정 저장", use_container_width=True, type="primary"):
    save_recruiter_config({
        "positions": st.session_state.recruiter_positions,
        "general_criteria": general_criteria.strip(),
    })
    st.success("✅ 채용 설정이 저장되었습니다. 다음 면접부터 적용됩니다.")

if config.get("updated_at"):
    st.caption(f"마지막 저장: {config['updated_at']}")

st.divider()
if st.button("로그아웃", key="recruiter_logout"):
    st.session_state.recruiter_authenticated = False
    st.session_state.pop("recruiter_positions", None)
    st.rerun()
