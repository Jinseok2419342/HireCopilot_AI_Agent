"""presentation.html → presentation.pdf (Chrome headless 사용)"""
import os, subprocess, tempfile, sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(BASE, "presentation.html")
OUT  = os.path.join(BASE, "presentation.pdf")

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 원본 HTML을 읽어 인쇄용으로 수정
with open(SRC, encoding="utf-8") as f:
    html = f.read()

# 이미지 경로를 절대 경로로 변환
img_dir = os.path.join(BASE, "img").replace("\\", "/")
html = html.replace('src="img/', f'src="file:///{img_dir}/')

# 인쇄용 CSS 삽입
PRINT_CSS = """
<style>
@media print {
  @page { size: 1280px 720px; margin: 0; }
  body { overflow: visible !important; }
  .nav-btn, #counter, #progress { display: none !important; }
  .deck { height: auto !important; }
  .slide {
    position: relative !important;
    opacity: 1 !important;
    transform: none !important;
    pointer-events: all !important;
    height: 720px !important;
    width: 1280px !important;
    page-break-after: always !important;
    break-after: page !important;
    overflow: hidden !important;
  }
  .slide:last-child { page-break-after: auto !important; break-after: auto !important; }
}
</style>
"""
html = html.replace("</head>", PRINT_CSS + "\n</head>")

# 임시 파일에 저장
with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False,
                                  encoding="utf-8", dir=BASE) as tmp:
    tmp.write(html)
    tmp_path = tmp.name

try:
    file_url = "file:///" + tmp_path.replace("\\", "/")
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={OUT}",
        "--print-to-pdf-no-header",
        "--no-pdf-header-footer",
        file_url,
    ]
    print("PDF 생성 중...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if os.path.exists(OUT):
        size_kb = os.path.getsize(OUT) // 1024
        print(f"완료: presentation.pdf ({size_kb} KB)")
    else:
        print("오류:", result.stderr[:500])
        sys.exit(1)
finally:
    os.unlink(tmp_path)
