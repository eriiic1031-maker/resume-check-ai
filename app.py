# -*- coding: utf-8 -*-
"""
총무 취업 AI V3
- 사람인 / 캐치 / 잡코리아 공개 채용 페이지에서 총무 관련 공고 수집
- 총무 관련 공고만 1차 필터링
- Ollama 로 내 경력과 비교
- 결과를 Streamlit 화면에 표시
- 선택한 결과를 네이버 메일로 발송

실행:
    python -m streamlit run app.py

필요 패키지:
    pip install streamlit python-dotenv requests playwright

최초 1회:
    python -m playwright install chromium

.env 예시:
    NAVER_EMAIL=본인네이버메일
    NAVER_APP_PASSWORD=네이버앱비밀번호
    RECEIVER_EMAIL=받을메일주소
"""

import os
import re
import html
import smtplib
import time
from urllib.parse import quote, urljoin

import requests
import streamlit as st
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    st.error(
        "Playwright가 설치되어 있지 않습니다.\n\n"
        "PowerShell에서 아래 명령어를 실행하세요.\n\n"
        "pip install playwright\n"
        "python -m playwright install chromium"
    )
    st.stop()


# =========================================================
# 1. 기본 설정
# =========================================================

load_dotenv()

APP_TITLE = "🤖 총무 취업 AI V3"

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"

NAVER_EMAIL = os.getenv("NAVER_EMAIL", "")
NAVER_APP_PASSWORD = os.getenv("NAVER_APP_PASSWORD", "")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL", "")

# 공개 채용 페이지
SARARAMIN_HOME = "https://www.saramin.co.kr/zf_user/"
SARARAMIN_SEARCH = (
    "https://www.saramin.co.kr/zf_user/jobs/list/"
    "job-category?cat_mcls=4&nomo=1"
)

CATCH_HOME = "https://www.catch.co.kr/"
CATCH_SEARCH = "https://www.catch.co.kr/NCS/RecruitSearch?search={keyword}"

JOBKOREA_HOME = "https://www.jobkorea.co.kr/"
JOBKOREA_SEARCH = (
    "https://www.jobkorea.co.kr/Search/?stext={keyword}"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36 Edg/154.0.0.0"
    )
}


# =========================================================
# 2. 내 경력 정보
# =========================================================

MY_PROFILE = """
[지원자 경력]
- 총무·경영지원 경력 3년 이상
- 총무기획 및 전사 운영지원
- 총무 제규정 수립/개정 및 정책관리
- 자산/비품 관리
- 시설 및 사옥 운영
- 임대차 및 공간 운영
- 업무용 차량 및 임원 차량 관리
- 수행기사 운영 및 운행일지/수당 관리
- 물적보안 관리
- CCTV, 출입통제, 경비인력 운영
- 국내/해외 출장 및 숙소 관리
- 계약 및 구매
- 복리후생 운영
- 전사 행사 운영
- 예산 품의 및 운영현황 관리
- ERP 업무 프로세스 개선
- 조직개편 및 사옥 이전
- 약 900명 규모 사옥 이전을 무중단으로 수행
- 삼성그룹사 근무 경험

[대표 성과/경험]
1. 원가혁신 TF
   - 본사 공간배치 효율화
   - 회의실/업무환경 개선
   - 차량/회의실 예약시스템 개선

2. 조직개편 및 사옥 이전
   - AutoCAD 기반 자리배치
   - 공사/이사 일정 통합
   - 약 900명 규모 사옥 이전을 무중단으로 수행

3. 복리후생 및 비용 개선
   - 복리후생 업체 변경
   - 비용 구조 개선 및 절감

4. 입주사 협의체
   - 입주사 커뮤니케이션
   - 사옥 환경 개선
   - 냉방/가습 관련 환경 문제 개선

5. 물적보안
   - CCTV
   - 출입통제
   - 경비인력
   - 본사 및 현장 보안 운영
   - 삼성그룹 보안 기준 Follow-up

6. 총무 운영
   - 신규입사자 총무 교육자료
   - 임원행사
   - 차량/수행기사 운영
   - 계약/구매
   - 자산/비품
   - 전산/통신장비
"""


# =========================================================
# 3. 총무 관련 키워드
# =========================================================

# 제목 또는 공고 본문에 아래 키워드가 있으면 총무 후보로 판단
PRIMARY_KEYWORDS = [
    "총무",
    "경영지원",
    "general affairs",
    "general affair",
]

SECONDARY_KEYWORDS = [
    "자산관리",
    "시설관리",
    "사옥관리",
    "비품관리",
    "복리후생",
    "법인차량",
    "차량관리",
    "수행기사",
    "보안관리",
    "cctv",
    "출입통제",
    "경비",
    "임대차",
    "사무환경",
    "구매관리",
    "구매",
    "행사운영",
    "office management",
]


# =========================================================
# 4. 공통 함수
# =========================================================

def clean_text(text: str) -> str:
    """웹페이지에서 가져온 텍스트를 정리."""
    if not text:
        return ""

    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def unique_keep_order(items):
    result = []
    seen = set()

    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)

    return result


def get_lines(text: str):
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]


def find_value_after_label(text: str, labels):
    """
    '경력', '근무형태', '근무지역' 같은 라벨 다음 값을 추출.
    페이지 구조가 달라도 최대한 안전하게 동작하도록 작성.
    """
    lines = get_lines(text)

    for i, line in enumerate(lines):
        normalized = line.replace(" ", "").lower()

        for label in labels:
            label_normalized = label.replace(" ", "").lower()

            if normalized == label_normalized:
                if i + 1 < len(lines):
                    return lines[i + 1][:150]

            if normalized.startswith(label_normalized + ":"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value[:150]

    return ""


def is_general_affairs_job(title: str, body: str, search_keyword: str = "총무"):
    """
    총무/경영지원 관련 공고인지 1차 판별.
    사람인처럼 범위가 넓은 직무 카테고리도 있기 때문에
    별도의 키워드 필터를 적용한다.
    """
    text = f"{title}\n{body}".lower()

    # 사용자가 직접 검색한 키워드도 포함
    if search_keyword:
        if search_keyword.lower() in text:
            return True

    # 핵심 총무 키워드
    for keyword in PRIMARY_KEYWORDS:
        if keyword.lower() in text:
            return True

    # 보조 키워드는 2개 이상 있을 경우 총무 후보로 인정
    secondary_count = 0

    for keyword in SECONDARY_KEYWORDS:
        if keyword.lower() in text:
            secondary_count += 1

    return secondary_count >= 2


def extract_deadline(body: str):
    """채용 마감일을 최대한 간단하게 추출."""
    lines = get_lines(body)

    for i, line in enumerate(lines):
        if any(
            keyword in line
            for keyword in ["접수기간", "접수 기간", "마감일", "채용기간"]
        ):
            if ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    return value[:100]

            if i + 1 < len(lines):
                return lines[i + 1][:100]

    # 날짜 형태를 직접 찾음
    match = re.search(
        r"(20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2}"
        r".{0,20}?"
        r"(?:20\d{2}[.\-/]\d{1,2}[.\-/]\d{1,2})?)",
        body,
    )

    if match:
        return match.group(1)[:100]

    return "공고에서 확인 필요"


def extract_company_and_title(page, body: str, site: str):
    """
    채용 상세 페이지마다 HTML 구조가 달라서
    h1 → og:title → 페이지 제목 → 본문 순으로 보완한다.
    """
    title = ""
    company = ""

    # h1
    try:
        h1_list = page.locator("h1").all_inner_texts()
        h1_list = [clean_text(x) for x in h1_list if clean_text(x)]

        if h1_list:
            title = h1_list[0]
    except Exception:
        pass

    # og:title
    og_title = ""
    try:
        og_title = page.locator(
            'meta[property="og:title"]'
        ).get_attribute("content") or ""
        og_title = clean_text(og_title)
    except Exception:
        pass

    # document.title
    page_title = ""
    try:
        page_title = clean_text(page.title())
    except Exception:
        pass

    # 사이트별 보완
    candidates = unique_keep_order([
        og_title,
        page_title,
    ])

    for candidate in candidates:
        # "회사명 | 공고명" 형태
        if "|" in candidate:
            parts = [
                clean_text(x)
                for x in candidate.split("|")
                if clean_text(x)
            ]

            if len(parts) >= 2:
                if not company:
                    company = parts[0]
                if not title:
                    title = parts[-1]

        # "공고명 - 사람인" 같은 형태
        if not title:
            candidate2 = re.sub(
                r"\s*[-|]\s*(사람인|캐치|잡코리아).*$",
                "",
                candidate,
                flags=re.IGNORECASE,
            )
            if candidate2:
                title = candidate2.strip()

    # 제목이 지나치게 길거나 사이트 공통 제목이면 본문에서 보완
    generic_titles = {
        "채용정보",
        "채용공고",
        "전체 채용공고",
        "잡코리아",
        "사람인",
        "캐치",
    }

    if not title or title in generic_titles:
        lines = get_lines(body)

        # 너무 짧은 메뉴 문구는 제외
        for line in lines[:80]:
            if (
                len(line) >= 4
                and line not in generic_titles
                and "로그인" not in line
                and "회원가입" not in line
            ):
                title = line
                break

    # 회사명이 없으면 본문 초반에서 추정
    if not company:
        lines = get_lines(body)

        for line in lines[:80]:
            if (
                len(line) >= 2
                and len(line) <= 80
                and line != title
                and "채용" not in line
                and "로그인" not in line
                and "회원가입" not in line
                and "검색" not in line
            ):
                company = line
                break

    if not company:
        company = "회사명 확인 필요"

    if not title:
        title = "채용공고 제목 확인 필요"

    return company[:150], title[:200]


def build_job(site, url, title="", company="", body="", page=None):
    """
    상세 페이지에서 하나의 공고 데이터 생성.
    """
    body = clean_text(body)

    if page is not None:
        extracted_company, extracted_title = extract_company_and_title(
            page, body, site
        )

        if not company:
            company = extracted_company

        if not title:
            title = extracted_title

    career = find_value_after_label(
        body,
        ["경력", "경력사항", "채용경력"]
    )

    employment_type = find_value_after_label(
        body,
        ["고용형태", "근무형태", "채용형태"]
    )

    location = find_value_after_label(
        body,
        ["근무지역", "근무 지역", "근무지", "지역"]
    )

    deadline = extract_deadline(body)

    # Ollama에 너무 긴 페이지 전체를 전달하지 않도록 제한
    description = body[:12000]

    return {
        "site": site,
        "company": company or "회사명 확인 필요",
        "title": title or "제목 확인 필요",
        "career": career or "공고에서 확인 필요",
        "employment_type": employment_type or "공고에서 확인 필요",
        "location": location or "공고에서 확인 필요",
        "deadline": deadline,
        "description": description,
        "url": url,
    }


# =========================================================
# 5. 사이트 검색 URL
# =========================================================

def get_search_urls(keyword, use_saramin, use_catch, use_jobkorea):
    urls = []

    if use_saramin:
        # 사람인은 총무/사무 관련 직무 카테고리에서 수집 후
        # 아래에서 총무 키워드로 2차 필터링한다.
        urls.append(
            (
                "사람인",
                SARARAMIN_SEARCH,
            )
        )

    if use_catch:
        urls.append(
            (
                "캐치",
                CATCH_SEARCH.format(keyword=quote(keyword)),
            )
        )

    if use_jobkorea:
        urls.append(
            (
                "잡코리아",
                JOBKOREA_SEARCH.format(keyword=quote(keyword)),
            )
        )

    return urls


# =========================================================
# 6. 검색 결과에서 상세 페이지 링크 추출
# =========================================================

def extract_job_links(page, site):
    """
    사이트 HTML의 모든 a 태그를 확인해 채용 상세 링크 후보를 찾는다.
    사이트 DOM이 변경되어도 비교적 버틸 수 있도록 URL 패턴 중심으로 처리.
    """
    anchors = page.locator("a").evaluate_all(
        """
        elements => elements.map(a => ({
            href: a.href || "",
            text: (a.innerText || a.textContent || "").trim()
        }))
        """
    )

    results = []
    seen = set()

    for item in anchors:
        href = (item.get("href") or "").strip()
        text = clean_text(item.get("text") or "")

        if not href:
            continue

        if site == "사람인":
            # 사람인 채용 상세 URL
            if (
                "saramin.co.kr" in href
                and "/zf_user/jobs/" in href
                and (
                    "rec_idx=" in href
                    or "/view" in href
                )
            ):
                if href not in seen:
                    seen.add(href)
                    results.append({
                        "url": href,
                        "text": text,
                    })

        elif site == "캐치":
            if (
                "catch.co.kr" in href
                and (
                    "/NCS/RecruitInfoDetails/" in href
                    or "/RecruitInfoDetails/" in href
                )
            ):
                if href not in seen:
                    seen.add(href)
                    results.append({
                        "url": href,
                        "text": text,
                    })

        elif site == "잡코리아":
            if (
                "jobkorea.co.kr" in href
                and (
                    "/Recruit/GI_Read/" in href
                    or "/Recruit/GI_Read/" in href
                )
            ):
                if href not in seen:
                    seen.add(href)
                    results.append({
                        "url": href,
                        "text": text,
                    })

    return results


# =========================================================
# 7. 검색 페이지 스크롤
# =========================================================

def scroll_search_page(page, rounds=5):
    """
    채용사이트의 lazy loading을 고려해 여러 번 스크롤한다.
    """
    for _ in range(rounds):
        try:
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(900)
        except Exception:
            break


# =========================================================
# 8. 실제 채용공고 수집
# =========================================================

def collect_jobs(
    keyword,
    use_saramin=True,
    use_catch=True,
    use_jobkorea=True,
    max_jobs_per_site=10,
    headless=True,
):
    """
    사람인/캐치/잡코리아 검색 페이지 → 상세 페이지 → 공고 데이터.
    """
    all_jobs = []
    errors = []

    search_urls = get_search_urls(
        keyword,
        use_saramin,
        use_catch,
        use_jobkorea,
    )

    if not search_urls:
        return [], ["최소 1개의 채용사이트를 선택해주세요."]

    with sync_playwright() as p:
        browser = None

        try:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="ko-KR",
                viewport={"width": 1440, "height": 1000},
            )

            search_page = context.new_page()
            search_page.set_default_timeout(15000)

            detail_page = context.new_page()
            detail_page.set_default_timeout(15000)

            for site, search_url in search_urls:
                try:
                    st.write(f"🔎 **{site} 검색 중...**")

                    search_page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )

                    # JS로 공고가 생성되는 사이트를 고려
                    search_page.wait_for_timeout(2500)
                    scroll_search_page(search_page, rounds=5)

                    links = extract_job_links(
                        search_page,
                        site,
                    )

                    if not links:
                        errors.append(
                            f"{site}: 채용 상세 링크를 찾지 못했습니다. "
                            "사이트 구조가 변경되었거나 검색 결과가 로딩되지 않았을 수 있습니다."
                        )
                        continue

                    # 링크 수 제한
                    links = links[:max_jobs_per_site]

                    progress = st.progress(
                        0,
                        text=f"{site} 상세 공고 확인 중..."
                    )

                    collected_count = 0

                    for index, item in enumerate(links):
                        url = item["url"]

                        try:
                            detail_page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=30000,
                            )

                            detail_page.wait_for_timeout(1200)

                            body = detail_page.locator(
                                "body"
                            ).inner_text(timeout=10000)

                            body = clean_text(body)

                            company, title = extract_company_and_title(
                                detail_page,
                                body,
                                site,
                            )

                            # 검색 결과 링크 텍스트가 더 명확한 경우
                            link_text = clean_text(item.get("text", ""))

                            if (
                                link_text
                                and len(link_text) >= 4
                                and "채용" in link_text
                            ):
                                if len(link_text) < len(title) or (
                                    title == "채용공고 제목 확인 필요"
                                ):
                                    title = link_text

                            # 총무 관련 여부 1차 필터
                            if not is_general_affairs_job(
                                title,
                                body,
                                keyword,
                            ):
                                progress.progress(
                                    (index + 1) / len(links),
                                    text=(
                                        f"{site}: {index + 1}/{len(links)} "
                                        "총무 관련 공고 필터링"
                                    ),
                                )
                                continue

                            job = build_job(
                                site=site,
                                url=url,
                                title=title,
                                company=company,
                                body=body,
                            )

                            all_jobs.append(job)
                            collected_count += 1

                            progress.progress(
                                (index + 1) / len(links),
                                text=(
                                    f"{site}: {index + 1}/{len(links)} "
                                    f"총무 공고 {collected_count}건 발견"
                                ),
                            )

                            # 사이트에 과도한 요청을 보내지 않도록 간격
                            time.sleep(0.7)

                        except PlaywrightTimeoutError:
                            errors.append(
                                f"{site}: 상세페이지 시간초과 - {url}"
                            )
                        except Exception as e:
                            errors.append(
                                f"{site}: 상세페이지 오류 - {str(e)[:120]}"
                            )

                    progress.empty()

                except PlaywrightTimeoutError:
                    errors.append(
                        f"{site}: 검색 페이지 접속 시간초과"
                    )
                except Exception as e:
                    errors.append(
                        f"{site}: 검색 오류 - {str(e)[:200]}"
                    )

            # URL 기준 중복 제거
            unique_jobs = []
            seen_urls = set()

            for job in all_jobs:
                if job["url"] in seen_urls:
                    continue

                seen_urls.add(job["url"])
                unique_jobs.append(job)

            all_jobs = unique_jobs

        finally:
            if browser is not None:
                browser.close()

    return all_jobs, errors


# =========================================================
# 9. Ollama 확인
# =========================================================

def check_ollama():
    try:
        response = requests.get(
            "http://localhost:11434/api/tags",
            timeout=5,
        )

        if response.status_code != 200:
            return False, "Ollama 서버에 연결할 수 없습니다."

        data = response.json()
        models = [
            model.get("name", "")
            for model in data.get("models", [])
        ]

        if not models:
            return False, "Ollama에 설치된 모델이 없습니다."

        model_exists = any(
            OLLAMA_MODEL in model
            for model in models
        )

        if not model_exists:
            return (
                False,
                f"'{OLLAMA_MODEL}' 모델이 없습니다. "
                f"PowerShell에서 'ollama pull {OLLAMA_MODEL}'을 실행하세요."
            )

        return True, f"Ollama 정상 / {OLLAMA_MODEL} 사용 가능"

    except Exception as e:
        return False, f"Ollama 연결 오류: {str(e)}"


# =========================================================
# 10. Ollama로 공고와 내 경력 비교
# =========================================================

def analyze_job(job):
    prompt = f"""
당신은 총무/경영지원 채용공고를 분석하는 AI입니다.

아래 지원자의 실제 경력과 채용공고를 비교하세요.

{MY_PROFILE}

[채용공고]
사이트: {job['site']}
회사명: {job['company']}
채용제목: {job['title']}
경력조건: {job['career']}
고용형태: {job['employment_type']}
근무지역: {job['location']}
마감정보: {job['deadline']}

[채용공고 상세]
{job['description'][:9000]}

반드시 아래 형식으로 한국어로 답하세요.

[총무 직무 적합도]
높음 / 보통 / 낮음 중 하나

[직접 연결되는 경력]
지원자의 경력 중 채용공고와 직접 연결되는 경험을 3~5개 작성

[강점]
이 공고에 지원할 때 강조할 수 있는 경험을 작성

[부족하거나 확인이 필요한 부분]
채용공고에는 있지만 지원자 경력에서 명확하게 확인되지 않는 항목을 작성

[지원서 강조 키워드]
자기소개서나 경력기술서에서 강조하면 좋은 키워드 5개 이내

[한줄 판단]
지원자의 총무 경력과 이 공고의 업무가 어떻게 연결되는지 한 문장으로 작성

주의:
- 채용공고에 없는 내용을 임의로 만들지 마세요.
- 지원자의 경력에도 없는 경험을 있다고 말하지 마세요.
- 회사나 채용공고에 대한 추측을 하지 마세요.
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
            },
            timeout=180,
        )

        response.raise_for_status()

        data = response.json()
        result = data.get("response", "").strip()

        if not result:
            return "Ollama가 분석 결과를 반환하지 않았습니다."

        return result

    except requests.exceptions.ConnectionError:
        return (
            "Ollama 연결 실패\n\n"
            "Ollama가 실행 중인지 확인해주세요."
        )

    except requests.exceptions.Timeout:
        return "Ollama 분석 시간이 초과되었습니다."

    except Exception as e:
        return f"Ollama 분석 오류: {str(e)}"


# =========================================================
# 11. 이메일 HTML
# =========================================================

def make_email_html(analyzed_jobs):
    html_parts = []

    html_parts.append("""
    <html>
    <body style="
        font-family: Arial, 'Malgun Gothic', sans-serif;
        line-height: 1.7;
        color: #222;
    ">
        <h2>🤖 총무 취업 AI - 채용공고 분석 결과</h2>
        <p>
            사람인 / 캐치 / 잡코리아의 공개 채용공고 중
            총무 관련 공고를 수집하여 내 경력과 비교한 결과입니다.
        </p>
        <hr>
    """)

    for index, job in enumerate(analyzed_jobs, 1):
        description = job.get("analysis", "")
        safe_analysis = html.escape(description)
        safe_title = html.escape(job["title"])
        safe_company = html.escape(job["company"])
        safe_site = html.escape(job["site"])
        safe_career = html.escape(job["career"])
        safe_employment = html.escape(job["employment_type"])
        safe_location = html.escape(job["location"])
        safe_deadline = html.escape(job["deadline"])
        safe_url = html.escape(job["url"], quote=True)

        html_parts.append(f"""
        <div style="
            border:1px solid #ddd;
            border-radius:10px;
            padding:18px;
            margin:20px 0;
        ">
            <h3>{index}. {safe_company}</h3>

            <p>
                <strong>채용제목:</strong> {safe_title}<br>
                <strong>사이트:</strong> {safe_site}<br>
                <strong>경력:</strong> {safe_career}<br>
                <strong>고용형태:</strong> {safe_employment}<br>
                <strong>근무지역:</strong> {safe_location}<br>
                <strong>마감:</strong> {safe_deadline}
            </p>

            <p>
                <a href="{safe_url}" target="_blank">
                    🔗 채용공고 바로가기
                </a>
            </p>

            <h4>AI 분석</h4>
            <pre style="
                white-space:pre-wrap;
                font-family:Arial, 'Malgun Gothic', sans-serif;
            ">{safe_analysis}</pre>
        </div>
        """)

    html_parts.append("""
        <hr>
        <p style="font-size:12px;color:#777;">
            본 메일은 공개 채용 페이지에서 수집한 정보를
            Ollama 로 분석하여 생성했습니다.
        </p>
    </body>
    </html>
    """)

    return "\n".join(html_parts)


# =========================================================
# 12. 네이버 메일 발송
# =========================================================

def send_naver_email(subject, html_body):
    if not NAVER_EMAIL:
        return False, "NAVER_EMAIL이 .env에 없습니다."

    if not NAVER_APP_PASSWORD:
        return False, "NAVER_APP_PASSWORD가 .env에 없습니다."

    if not RECEIVER_EMAIL:
        return False, "RECEIVER_EMAIL이 .env에 없습니다."

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = NAVER_EMAIL
    message["To"] = RECEIVER_EMAIL

    message.attach(
        MIMEText(
            html_body,
            "html",
            "utf-8",
        )
    )

    try:
        with smtplib.SMTP_SSL(
            "smtp.naver.com",
            465,
            timeout=30,
        ) as server:

            server.login(
                NAVER_EMAIL,
                NAVER_APP_PASSWORD,
            )

            server.sendmail(
                NAVER_EMAIL,
                RECEIVER_EMAIL,
                message.as_string(),
            )

        return True, "메일 발송 완료"

    except Exception as e:
        return False, f"메일 발송 실패: {str(e)}"


# =========================================================
# 13. Streamlit 화면
# =========================================================

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🤖",
    layout="wide",
)

st.title(APP_TITLE)

st.markdown(
    """
### 내 총무 경력과 실제 채용공고를 자동으로 비교합니다.

**채용사이트 → 실제 공고 수집 → 총무 필터 → Ollama 분석 → 네이버 메일**
"""
)

st.info(
    "현재 버전은 테스트용 채용공고가 아니라 "
    "사람인·캐치·잡코리아의 공개 채용 페이지에서 "
    "실제 공고를 가져오는 방식입니다."
)

# ---------------------------------------------------------
# 사이드바
# ---------------------------------------------------------

with st.sidebar:
    st.header("⚙️ 검색 설정")

    keyword = st.text_input(
        "검색 키워드",
        value="총무",
        help="예: 총무, 경영지원, GA",
    )

    st.subheader("채용사이트")

    use_saramin = st.checkbox(
        "사람인",
        value=True,
    )

    use_catch = st.checkbox(
        "캐치",
        value=True,
    )

    use_jobkorea = st.checkbox(
        "잡코리아",
        value=True,
    )

    max_jobs_per_site = st.slider(
        "사이트별 상세공고 확인 개수",
        min_value=3,
        max_value=30,
        value=10,
        step=1,
    )

    show_browser = st.checkbox(
        "브라우저 화면 보기",
        value=False,
        help="문제 발생 시 체크하면 실제 브라우저가 열립니다.",
    )

    st.divider()

    st.subheader("🤖 AI")

    st.write(f"모델: `{OLLAMA_MODEL}`")

    ollama_ok, ollama_message = check_ollama()

    if ollama_ok:
        st.success(ollama_message)
    else:
        st.error(ollama_message)

# ---------------------------------------------------------
# 현재 경력 확인
# ---------------------------------------------------------

with st.expander("📄 현재 AI가 사용하는 내 경력 확인"):
    st.text(MY_PROFILE)

# ---------------------------------------------------------
# 검색 버튼
# ---------------------------------------------------------

if "jobs" not in st.session_state:
    st.session_state.jobs = []

if "analyzed_jobs" not in st.session_state:
    st.session_state.analyzed_jobs = []

if "search_errors" not in st.session_state:
    st.session_state.search_errors = []


search_clicked = st.button(
    "🔎 실제 채용공고 검색하기",
    type="primary",
    use_container_width=True,
)

if search_clicked:
    if not keyword.strip():
        st.warning("검색 키워드를 입력해주세요.")
        st.stop()

    if not (
        use_saramin
        or use_catch
        or use_jobkorea
    ):
        st.warning("최소 1개의 채용사이트를 선택해주세요.")
        st.stop()

    with st.status(
        "실제 채용공고를 검색하고 있습니다...",
        expanded=True,
    ) as status:

        jobs, errors = collect_jobs(
            keyword=keyword.strip(),
            use_saramin=use_saramin,
            use_catch=use_catch,
            use_jobkorea=use_jobkorea,
            max_jobs_per_site=max_jobs_per_site,
            headless=not show_browser,
        )

        st.session_state.jobs = jobs
        st.session_state.analyzed_jobs = []
        st.session_state.search_errors = errors

        status.update(
            label=f"검색 완료 - 총 {len(jobs)}건",
            state="complete",
        )

# ---------------------------------------------------------
# 검색 결과
# ---------------------------------------------------------

jobs = st.session_state.jobs

if jobs:
    st.success(
        f"🎉 총 {len(jobs)}건의 총무 관련 실제 채용공고를 찾았습니다."
    )

    if st.session_state.search_errors:
        with st.expander("⚠️ 검색 중 발생한 안내"):
            for error in st.session_state.search_errors:
                st.write(f"- {error}")

    st.subheader("📋 수집된 채용공고")

    for index, job in enumerate(jobs):
        with st.expander(
            f"{index + 1}. [{job['site']}] "
            f"{job['company']} - {job['title']}"
        ):
            col1, col2 = st.columns(2)

            with col1:
                st.write(f"**사이트:** {job['site']}")
                st.write(f"**회사:** {job['company']}")
                st.write(f"**경력:** {job['career']}")
                st.write(f"**고용형태:** {job['employment_type']}")

            with col2:
                st.write(f"**근무지역:** {job['location']}")
                st.write(f"**마감:** {job['deadline']}")
                st.link_button(
                    "채용공고 바로가기",
                    job["url"],
                )

            st.caption(
                job["description"][:700]
                + ("..." if len(job["description"]) > 700 else "")
            )

    st.divider()

    # -----------------------------------------------------
    # AI 분석
    # -----------------------------------------------------

    st.subheader("🤖 내 경력과 비교")

    analyze_clicked = st.button(
        "🧠 전체 공고 AI 분석하기",
        type="primary",
        use_container_width=True,
    )

    if analyze_clicked:
        if not ollama_ok:
            st.error(
                "Ollama가 준비되지 않았습니다. "
                "사이드바의 Ollama 상태를 확인해주세요."
            )
            st.stop()

        analyzed_jobs = []

        progress = st.progress(
            0,
            text="AI 분석 준비 중..."
        )

        for index, job in enumerate(jobs):
            progress.progress(
                index / len(jobs),
                text=(
                    f"{index + 1}/{len(jobs)} "
                    f"{job['company']} - AI 분석 중..."
                ),
            )

            analysis = analyze_job(job)

            result = dict(job)
            result["analysis"] = analysis

            analyzed_jobs.append(result)

        progress.progress(
            1.0,
            text="AI 분석 완료"
        )

        st.session_state.analyzed_jobs = analyzed_jobs

    # -----------------------------------------------------
    # 분석 결과 출력
    # -----------------------------------------------------

    analyzed_jobs = st.session_state.analyzed_jobs

    if analyzed_jobs:
        st.success(
            f"AI 분석 완료: {len(analyzed_jobs)}건"
        )

        for index, job in enumerate(analyzed_jobs):
            with st.expander(
                f"🤖 {index + 1}. "
                f"{job['company']} - {job['title']}",
                expanded=(index == 0),
            ):
                st.write(
                    f"**{job['site']} | "
                    f"{job['career']} | "
                    f"{job['location']}**"
                )

                st.link_button(
                    "🔗 채용공고 원문 보기",
                    job["url"],
                )

                st.markdown("---")

                st.markdown(
                    job["analysis"]
                )

        # -------------------------------------------------
        # 이메일 발송
        # -------------------------------------------------

        st.divider()

        st.subheader("📧 네이버 메일")

        if NAVER_EMAIL and RECEIVER_EMAIL:
            st.write(
                f"발송 계정: `{NAVER_EMAIL}`"
            )
            st.write(
                f"수신 계정: `{RECEIVER_EMAIL}`"
            )

        send_clicked = st.button(
            "📨 분석 결과 네이버 메일로 보내기",
            use_container_width=True,
        )

        if send_clicked:
            email_html = make_email_html(
                analyzed_jobs
            )

            subject = (
                f"[총무 취업 AI] "
                f"총무 관련 채용공고 {len(analyzed_jobs)}건 분석 결과"
            )

            success, message = send_naver_email(
                subject,
                email_html,
            )

            if success:
                st.success(message)
            else:
                st.error(message)

else:
    st.info(
        "위의 **🔎 실제 채용공고 검색하기** 버튼을 눌러 "
        "사람인·캐치·잡코리아에서 공고를 가져오세요."
    )

# =========================================================
# 14. 하단 안내
# =========================================================

st.divider()

st.caption(
    "총무 취업 AI V3 | "
    "공개 채용 페이지 수집 + Ollama 로컬 AI 분석 + Naver SMTP"
)

st.caption(
    "※ 채용사이트의 페이지 구조가 변경되면 수집 기능을 수정해야 할 수 있습니다."
)
