# 🚀 처음 세팅 및 실행 방법 (Windows / PowerShell)

본 프로젝트(`HireCopilot_AI_Agent`)를 로컬 Windows 환경에서 세팅하고 실행하기 위한 가이드라인입니다.

---

### 1단계 — 가상환경 생성 및 활성화

프로젝트 루트 폴더로 이동한 후, Python 가상환경을 생성하고 활성화합니다.

```powershell
# 프로젝트 폴더로 이동 (사용자 환경에 맞게 조정 가능)
cd C:\Users\pppp\Documents\GitHub\HireCopilot_AI_Agent

# 가상환경 생성
python -m venv .venv

# 가상환경 활성화
.\.venv\Scripts\Activate.ps1
```

> [!TIP]
> PowerShell에서 보안 정책 오류로 스크립트 실행이 제한되는 경우, 아래 명령을 터미널에 한 번 실행해 줍니다.
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
> ```

---

### 2단계 — 필수 패키지 설치

의존성 라이브러리들을 가상환경 내에 설치합니다.

```powershell
pip install -r requirements.txt
```

---

### 3단계 — 환경 변수 설정 (.env)

프로젝트 루트 폴더에 `.env` 파일을 새로 생성하고 아래의 설정값을 복사한 후 알맞게 채워 넣습니다.

```env
# OpenAI API 키. 비워두면 7개의 예시 질문으로 동작하는 데모(Dummy) 모드로 실행됩니다.
OPENAI_API_KEY=sk-...

# 사용할 OpenAI GPT 모델 지정
OPENAI_MODEL=gpt-4o-mini

# Google Apps Script 웹훅 URL (스프레드시트 자동 기록 API)
ZAPIER_WEBHOOK_URL=https://script.google.com/macros/s/XXXXXX/exec

# 개발자 모드(실시간 채점 시각화) 토글 활성화 암호 (비워둘 시 패스워드 검증을 건너뜁니다)
DEV_TOGGLE_PASSWORD=1234

# 채용 담당자 설정 페이지(recruiter.py) 접근 암호 (비워둘 시 패스워드 검증을 건너뜁니다)
RECRUITER_PASSWORD=1234
```

> [!WARNING]
> `.env` 설정값을 수정한 경우에는 반드시 실행 중인 Streamlit 서버를 재시작(`Ctrl + C` 누른 후 다시 실행)해야 변경 내용이 적용됩니다.

---

### 4단계 — 어플리케이션 실행

본 서비스는 지원자용 인터뷰 앱과 채용 담당자용 설정 관리 앱 두 가지로 분리되어 구동할 수 있습니다.

#### ① 지원자 면접 앱 (Main Application)
```powershell
streamlit run app.py
```
- 실행 후 브라우저에서 `http://localhost:8501`에 접속하여 테스트를 시작합니다.

#### ② 채용 담당자 설정 앱 (Recruiter Admin Portal)
새로운 PowerShell 창을 열어 가상환경을 활성화한 후 다음 명령어를 실행합니다.
```powershell
streamlit run recruiter.py --server.port 8502
```
- 실행 후 브라우저에서 `http://localhost:8502`에 접속해 채용 기준을 제어합니다.

---

[← 메인 README.md로 돌아가기](README.md)
