import requests
import os
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup

SEEN_JOBS_FILE = "seen_jobs.json"

def load_seen_jobs() -> set:
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen_jobs(seen: set):
    # 최근 500개만 유지 (파일 무한 증가 방지)
    items = list(seen)[-500:]
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(items, f)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

WANTED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.wanted.co.kr/",
    "wanted-user-country": "KR",
    "wanted-user-language": "ko",
}

SARAMIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.saramin.co.kr/",
}

JOBKOREA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

WANTED_JOB_GROUPS = [("70", "디자인")]

SARAMIN_KEYWORDS = [
    "UX디자이너",
    "UI디자이너",
    "프로덕트디자이너",
]

JOBKOREA_KEYWORDS = [
    "UX디자이너",
    "UI디자이너",
    "프로덕트디자이너",
]

# ── 필터 설정 ──────────────────────────────────────────
# 서울 지역이 아닌 경우 제외 (위치 정보가 없으면 일단 포함)
def is_seoul(location: str) -> bool:
    if not location:
        return True
    return "서울" in location

# 경력 2~4년 범위 필터
def is_experience_match(text: str) -> bool:
    t = text.lower()

    # 신입 전용 제외
    if re.search(r'신입\s*전용|신입\s*모집|신입\s*채용|인턴', t):
        return False
    # "신입/경력"은 허용, 순수 신입만 제외
    if "신입" in t and "경력" not in t:
        return False

    # 시니어/리드/디렉터 직책 제외
    if re.search(r'시니어|senior|리드\s*디자|lead\s*design|헤드|head\s*of|디렉터|director', t):
        return False

    # "X년 이상" 패턴 추출 → X가 5 이상이면 제외
    for m in re.finditer(r'(\d+)\s*년\s*이상', t):
        if int(m.group(1)) >= 5:
            return False

    # "경력 X년" or "경력X년" 패턴 → X가 5 이상이면 제외
    for m in re.finditer(r'경력\s*(\d+)\s*년', t):
        if int(m.group(1)) >= 5:
            return False

    # "X-Y년" or "X~Y년" 범위 → 최솟값이 5 이상이면 제외
    for m in re.finditer(r'(\d+)\s*[-~]\s*(\d+)\s*년', t):
        if int(m.group(1)) >= 5:
            return False

    return True

# 자유출근제 또는 인하우스 관련 키워드 (공고 상세에서 확인)
FLEX_KEYWORDS = ["자유출근", "유연근무", "탄력근무", "플렉스", "flex"]
INHOUSE_KEYWORDS = ["인하우스", "in-house", "자사", "서비스", "플랫폼"]

def has_flex(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in FLEX_KEYWORDS)

def is_inhouse(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in INHOUSE_KEYWORDS)

# ──────────────────────────────────────────────────────


def fetch_wanted_detail(job_id: int) -> dict:
    """공고 상세 정보 (자유출근제·인하우스 확인용)"""
    try:
        resp = requests.get(
            f"https://www.wanted.co.kr/api/v4/jobs/{job_id}",
            headers=WANTED_HEADERS,
            timeout=8,
        )
        resp.raise_for_status()
        return resp.json().get("job", {})
    except Exception:
        return {}


def fetch_wanted():
    jobs = []
    for group_id, label in WANTED_JOB_GROUPS:
        try:
            resp = requests.get(
                "https://www.wanted.co.kr/api/v4/jobs",
                headers=WANTED_HEADERS,
                params={
                    "job_sort": "job.latest_order",
                    "country": "kr",
                    "job_group_id": group_id,
                    "limit": "30",
                    "offset": "0",
                },
                timeout=10,
            )
            resp.raise_for_status()
            for job in resp.json().get("data", []):
                position = job.get("position", "")

                # 직군 필터
                if not any(k in position for k in ["UX", "UI", "프로덕트", "Product", "서비스"]):
                    continue

                location = job.get("address", {}).get("location", "")

                # 서울 필터
                if not is_seoul(location):
                    continue

                company = job.get("company", {}).get("name", "")
                job_id = job.get("id")

                # 상세 페이지에서 경력·자유출근제·인하우스 확인
                detail = fetch_wanted_detail(job_id)
                detail_text = " ".join([
                    detail.get("detail", {}).get("intro", ""),
                    detail.get("detail", {}).get("main_tasks", ""),
                    detail.get("detail", {}).get("requirements", ""),
                    detail.get("detail", {}).get("benefits", ""),
                    " ".join(t.get("title", "") for t in detail.get("tags", [])),
                ])

                # 경력 필터 (제목 + 상세 전체 텍스트)
                if not is_experience_match(position + " " + detail_text):
                    continue

                flex = has_flex(detail_text)
                inhouse = is_inhouse(position + " " + detail_text)

                jobs.append({
                    "company": company,
                    "position": position,
                    "location": location,
                    "link": f"https://www.wanted.co.kr/wd/{job_id}",
                    "flex": flex,
                    "inhouse": inhouse,
                })
        except Exception as e:
            print(f"[원티드 오류] {e}")
    return jobs


def fetch_saramin():
    jobs = []
    seen = set()
    for keyword in SARAMIN_KEYWORDS:
        try:
            resp = requests.get(
                "https://www.saramin.co.kr/zf_user/search/recruit",
                headers=SARAMIN_HEADERS,
                params={
                    "searchType": "search",
                    "searchword": keyword,
                    "loc_mcd": "101000",  # 서울
                    "exp_cd": "1",        # 경력직
                },
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".item_recruit")[:10]:
                title_el = item.select_one(".job_tit a")
                company_el = item.select_one(".corp_name a")
                if not (title_el and company_el):
                    continue

                title = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True)
                href = title_el.get("href", "")
                if href and not href.startswith("http"):
                    href = "https://www.saramin.co.kr" + href

                item_text = item.get_text()

                if not is_experience_match(title + " " + item_text):
                    continue

                flex = has_flex(item_text)
                inhouse = is_inhouse(title + " " + item_text)

                key = (company, title)
                if key not in seen:
                    seen.add(key)
                    jobs.append({
                        "company": company,
                        "position": title,
                        "location": "서울",
                        "link": href,
                        "flex": flex,
                        "inhouse": inhouse,
                    })
        except Exception as e:
            print(f"[사람인 오류] {e}")
    return jobs


def fetch_jobkorea():
    jobs = []
    seen = set()
    for keyword in JOBKOREA_KEYWORDS:
        try:
            resp = requests.get(
                "https://www.jobkorea.co.kr/Search/",
                headers=JOBKOREA_HEADERS,
                params={"stext": keyword, "tabType": "recruit", "localCode": "I010101"},  # 서울
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".list-default .list-item")[:15]:
                title_el = item.select_one(".title")
                company_el = item.select_one(".name")
                link_el = item.select_one("a.title") or item.select_one("a")
                if not (title_el and company_el):
                    continue

                title = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True)
                href = link_el.get("href", "") if link_el else ""
                if href and not href.startswith("http"):
                    href = "https://www.jobkorea.co.kr" + href

                item_text = item.get_text()

                # 경력 필터 (제목 + 리스트 전체 텍스트)
                if not is_experience_match(title + " " + item_text):
                    continue

                flex = has_flex(item_text)
                inhouse = is_inhouse(title + " " + item_text)

                key = (company, title)
                if key not in seen:
                    seen.add(key)
                    jobs.append({
                        "company": company,
                        "position": title,
                        "location": "서울",
                        "link": href,
                        "flex": flex,
                        "inhouse": inhouse,
                    })
        except Exception as e:
            print(f"[잡코리아 오류] {e}")
    return jobs


def format_job_line(job):
    badges = []
    if job.get("flex"):
        badges.append("🕐자유출근")
    if job.get("inhouse"):
        badges.append("🏢인하우스")
    badge_str = " ".join(badges)

    line = f"• **[{job['company']}]** {job['position']}"
    if job.get("location"):
        line += f" · {job['location']}"
    if badge_str:
        line += f"  {badge_str}"
    line += f"\n  {job['link']}"
    return line


def send_to_discord(wanted, saramin, jobkorea):
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL 환경변수가 없습니다.")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")
    total = len(wanted) + len(saramin) + len(jobkorea)
    sections = []

    filter_summary = "📍서울 · 💼경력 2.5년+ · 🏢인하우스/스타트업 우선"

    if wanted:
        lines = "\n".join(format_job_line(j) for j in wanted[:10])
        sections.append(f"🔵 **원티드** ({len(wanted)}개)\n{lines}")

    if saramin:
        lines = "\n".join(format_job_line(j) for j in saramin[:10])
        sections.append(f"🟢 **사람인** ({len(saramin)}개)\n{lines}")

    if jobkorea:
        lines = "\n".join(format_job_line(j) for j in jobkorea[:10])
        sections.append(f"🔴 **잡코리아** ({len(jobkorea)}개)\n{lines}")

    if not sections:
        body = "오늘은 조건에 맞는 공고를 찾지 못했어요."
    else:
        body = "\n\n".join(sections)

    header = f"## 📋 {today} 디자이너 채용 공고 ({total}개)\n{filter_summary}\n\n"
    full_message = header + body

    chunks = []
    remaining = full_message
    while len(remaining) > 1900:
        split_at = remaining[:1900].rfind("\n")
        if split_at == -1:
            split_at = 1900
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    chunks.append(remaining)

    for chunk in chunks:
        resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk})
        print(f"Discord 전송 상태: {resp.status_code}")


if __name__ == "__main__":
    print("공고 수집 시작...")

    seen = load_seen_jobs()
    print(f"기존 확인된 공고: {len(seen)}개")

    wanted = fetch_wanted()
    saramin = fetch_saramin()
    jobkorea = fetch_jobkorea()

    # 새 공고만 필터링
    def filter_new(jobs):
        new = [j for j in jobs if j["link"] not in seen]
        return new

    new_wanted = filter_new(wanted)
    new_saramin = filter_new(saramin)
    new_jobkorea = filter_new(jobkorea)

    print(f"원티드: 전체 {len(wanted)}개 → 신규 {len(new_wanted)}개")
    print(f"사람인: 전체 {len(saramin)}개 → 신규 {len(new_saramin)}개")
    print(f"잡코리아: 전체 {len(jobkorea)}개 → 신규 {len(new_jobkorea)}개")

    send_to_discord(new_wanted, new_saramin, new_jobkorea)

    # seen 목록 업데이트
    for j in wanted + saramin + jobkorea:
        seen.add(j["link"])
    save_seen_jobs(seen)
    print("완료!")
