# 🚀 처음 세팅 및 실행 방법 (Windows / PowerShell)

---

### 1단계 — 가상환경

```powershell
cd C:\Users\6-112\Desktop\HireCopilot_AI_Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

PowerShell 실행 정책 오류 시:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

---

### 2단계 — 패키지 설치

```powershell
pip install -r requirements.txt
```

---

### 3단계 — `.env` 설정

`.env.example`을 `.env`로 복사 후 값을 채웁니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# gas/webhook_router.gs 배포 URL (필수 — 시트 저장/outbox)
GAS_WEBHOOK_URL=https://script.google.com/macros/s/XXXX/exec

# 2차 파이프라인 (선택 — outbox 알림용)
ADMIN_EMAIL=you@example.com
ADMIN_SLACK_USER_ID=U0XXXXXXX
NOTION_DATABASE_LABEL=2026 보류 합격자 목록

PIPELINE_MIN_GPA=3.0
PIPELINE_REQUIRE_GPA=true

DEV_TOGGLE_PASSWORD=1234
RECRUITER_PASSWORD=1234
```

> `.env` 변경 후 Streamlit **완전 재시작** 필요

---

### 4단계 — Google Apps Script

1. 스프레드시트 `1swaf7dyRsVRxepLJAXVoPO3YRNV0aPYmcBLL4_tPnbE` 열기
2. **확장 프로그램 → Apps Script**
3. `gas/webhook_router.gs` 내용 붙여넣기
4. **배포 → 새 배포 → 웹 앱** (실행: 나, 액세스: 모든 사용자)
5. URL → `GAS_WEBHOOK_URL`

---

### 5단계 — Zapier (선택, 앱 연결)

outbox 탭마다 **New Row → Gmail/Slack/...** ZAP 1개씩 생성.  
상세 매핑은 [README.md](README.md) 참고.

---

### 6단계 — 앱 실행

```powershell
streamlit run app.py
# http://localhost:8501

# 별도 터미널
streamlit run recruiter.py --server.port 8502
# http://localhost:8502
```

---

### 7단계 — 테스트

```powershell
python -m unittest tests/test_pipeline.py
```

---

[← README.md](README.md)
