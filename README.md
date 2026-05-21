# 🎓 HireCopilot — AI 채용 인터뷰 자동화 에이전트

> **학교 프로젝트 MVP** 

지원자가 AI 면접관과 한국어로 대화하고, 면접이 끝나면 구조화된 평가 리포트가 **자동으로 구글 스프레드시트에 기록**되는 Streamlit 기반 채용 자동화 에이전트입니다.

---

## ✨ 주요 특징

### 🤖 AI 면접 자동화
- **GPT-4o-mini** 기반 AI 면접관이 한국어 존댓말로 면접 진행
- 채용 담당자가 설정한 **포지션별 평가 기준**을 자동 반영
- STAR 방식(상황-과제-행동-결과) 꼬리질문 자동 생성
- 지원자 답변 **6~8개** 후 면접 자동 종료

### 📋 온보딩 입력 폼
- 면접 시작 전 이름, 이메일, 학력, 경력, 학점, 지원 포지션 수집
- 필수 항목 미입력 시 면접 시작 차단

### 📊 5개 루브릭 자동 채점 (1~5점)
| 항목 | 설명 |
|---|---|
| `culture_fit` | 회사 인재상 적합도 |
| `customer_response` | 고객 응대 마인드 및 문제 해결력 |
| `ownership` | 주인의식과 자발성 |
| `communication` | 답변 명확성과 공감 표현 |
| `learning_agility` | 피드백 수용력과 적응 능력 |

### 📤 구글 스프레드시트 자동 기록
- 면접 종료 시 **Google Apps Script 웹훅**으로 전체 결과 자동 전송
- 기록 항목: 시간, 이름, 이메일, 포지션, 학력, 학점, 경력, 채용 의견, 채용 추천 이유, 총점, 항목별 점수, 요약, 추천 다음 단계, 전체 대화록

### 👔 채용 담당자 설정 페이지 (`recruiter.py`)
- 포지션 추가/수정/삭제 및 **포지션별 AI 면접 중점 기준** 입력
- 공통 채용 기준 입력
- 설정이 `recruiter_config.json`에 저장 → 다음 면접부터 AI에 자동 반영
- 암호 인증 보호

### 🛠️ 개발자 모드
- 토글 활성화 시 암호 인증 필요
- 면접 진행 중 **실시간 점수 시각화** (컬러 progress bar)
- 채용 의견(🟢 추천 / 🟡 보류 / 🔴 비추천) 표시
- 전체 대화록 및 raw JSON 확인 가능

### 🎭 Dummy 모드
- `OPENAI_API_KEY` 없이도 미리 준비된 질문으로 UI 전체 시연 가능

---

## 📁 프로젝트 구조

```
HireCopilot_AI_Agent/
├── app.py                  # 지원자 면접 앱 (메인)
├── recruiter.py            # 채용 담당자 설정 앱
├── recruiter_config.json   # 채용 담당자 설정 저장 파일 (자동 생성)
├── requirements.txt        # Python 패키지 목록
├── .env                    # 환경 변수 (직접 생성)
└── README.md               # 본 문서
```

---

## 🚀 처음 세팅 방법 (Windows / PowerShell)

### 1단계 — 가상환경 생성 및 활성화

```powershell
cd C:\Users\pppp\Desktop\HireCopilot_AI_Agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

> PowerShell이 스크립트 실행을 막을 경우 아래 명령을 한 번 실행:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

### 2단계 — 패키지 설치

```powershell
pip install -r requirements.txt
```

### 3단계 — 환경 변수 설정

프로젝트 폴더에 `.env` 파일을 생성하고 아래 내용을 채웁니다:

```env
# OpenAI API 키. 비워두면 Dummy 모드로 실행됩니다.
OPENAI_API_KEY=sk-...

# 사용할 GPT 모델
OPENAI_MODEL=gpt-4o-mini

# Google Apps Script 웹훅 URL (스프레드시트 자동 기록)
ZAPIER_WEBHOOK_URL=https://script.google.com/macros/s/XXXXXX/exec

# 개발자 모드 활성화 암호 (비워두면 암호 없이 토글 가능)
DEV_TOGGLE_PASSWORD=your_dev_password

# 채용 담당자 페이지 접근 암호 (비워두면 암호 없이 접근 가능)
RECRUITER_PASSWORD=your_recruiter_password
```

> ⚠️ `.env` 파일을 수정한 뒤에는 **앱을 재시작**해야 적용됩니다 (`Ctrl+C` → 다시 실행).

### 4단계 — 앱 실행

**지원자 면접 앱:**
```powershell
streamlit run app.py
```
→ `http://localhost:8501` 에서 접속

**채용 담당자 설정 앱 (별도 실행):**
```powershell
streamlit run recruiter.py --server.port 8502
```
→ `http://localhost:8502` 에서 접속

---

## 🗂️ Google Apps Script 연동 설정

### Apps Script 코드

Google 스프레드시트를 열고 **확장 프로그램 → Apps Script**에 아래 코드를 붙여넣고 배포합니다:

```javascript
function doPost(e) {
  try {
    var sheet = SpreadsheetApp.openById("스프레드시트 아이디").getActiveSheet();
    var data = JSON.parse(e.postData.contents);

    sheet.appendRow([
      data.timestamp || "",
      data.candidate_name || "",
      data.candidate_email || "",
      data.position || "",
      data.degree || "",
      data.gpa || "",
      data.experience || "",
      data.fit_level || "",
      data.hiring_opinion || "",
      data.hiring_recommendation_reason || "",
      data.scores ? data.scores.overall : "",
      data.scores ? data.scores.culture_fit : "",
      data.scores ? data.scores.customer_response : "",
      data.scores ? data.scores.ownership : "",
      data.scores ? data.scores.communication : "",
      data.scores ? data.scores.learning_agility : "",
      data.summary || "",
      data.recommended_next_step || "",
      data.transcript || ""
    ]);

    return ContentService
      .createTextOutput(JSON.stringify({ result: "success" }))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ result: "error", message: err.toString() }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}
```

### 스프레드시트 헤더 (1행에 추가 권장)

| A | B | C | D | E | F | G | H | I | J | K | L | M | N | O | P | Q | R | S |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 타임스탬프 | 이름 | 이메일 | 지원포지션 | 학력 | 학점 | 경력 | 적합도 | 채용의견 | 채용추천이유 | 총점 | 문화적합도 | 고객응대 | 주인의식 | 커뮤니케이션 | 학습민첩성 | 요약 | 추천다음단계 | 전체대화록 |

### 배포 방법
1. Apps Script 편집기에서 **배포 → 새 배포** 클릭
2. 종류: **웹 앱**
3. 실행 계정: **나**
4. 액세스 권한: **모든 사용자**
5. 배포 후 생성된 URL을 `.env`의 `ZAPIER_WEBHOOK_URL`에 입력

---

## 📊 최종 평가 JSON 구조

```json
{
  "candidate_name": "홍길동",
  "candidate_email": "hong@example.com",
  "position": "IT 개발자",
  "degree": "학사 (4년제)",
  "gpa": "4.0 / 4.5",
  "experience": "1~3년",
  "timestamp": "2026-05-07T10:00:00+00:00",
  "scores": {
    "culture_fit": 4,
    "customer_response": 4,
    "ownership": 3,
    "communication": 5,
    "learning_agility": 4,
    "overall": 4.0
  },
  "fit_level": "possible_match",
  "hiring_opinion": "추천",
  "hiring_recommendation_reason": "커뮤니케이션과 학습 능력이 우수합니다...",
  "summary": "지원자는 ...",
  "strengths": ["명확한 의사소통", "..."],
  "concerns": ["주인의식 사례 부족", "..."],
  "recommended_next_step": "실무 면접 진행 권장",
  "transcript": "면접관: ...\n지원자: ..."
}
```

`fit_level` 값: `strong_match` / `possible_match` / `needs_human_review` / `weak_match`
`hiring_opinion` 값: `추천` / `보류` / `비추천`

---

## ⚙️ 채용 담당자 설정 사용법

1. `streamlit run recruiter.py --server.port 8502` 실행
2. `.env`의 `RECRUITER_PASSWORD`로 로그인
3. **포지션 추가**: 포지션 이름과 중점 평가 기준 입력
4. **공통 기준** 입력 (모든 포지션 공통 적용)
5. **설정 저장** 클릭 → `recruiter_config.json` 업데이트
6. 이후 `app.py` 면접에서 해당 포지션 선택 시 AI가 기준을 반영해 면접 진행


---

