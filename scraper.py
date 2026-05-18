import requests
import os
from datetime import datetime
from bs4 import BeautifulSoup

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

WANTED_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.wanted.co.kr/",
    "wanted-user-country": "KR",
    "wanted-user-language": "ko",
}

JUMPIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://jumpit.saramin.co.kr",
    "Referer": "https://jumpit.saramin.co.kr/",
}

JOBKOREA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 원티드 job_group_id: 70=디자인
# 점핏 jobCategory: 15=UI/UX 디자이너, 16=그래픽디자이너, 17=서비스기획
WANTED_JOB_GROUPS = [
    ("70", "디자인"),
]

JUMPIT_CATEGORIES = [
    (15, "UI/UX 디자이너"),
    (16, "그래픽/BX 디자이너"),
]

JOBKOREA_KEYWORDS = [
    "UX디자이너",
    "UI디자이너",
    "프로덕트디자이너",
]


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
                    "limit": "20",
                    "offset": "0",
                },
                timeout=10,
            )
            resp.raise_for_status()
            for job in resp.json().get("data", []):
                position = job.get("position", "")
                # 직군 필터: UX/UI 또는 프로덕트 디자이너
                if not any(k in position for k in ["UX", "UI", "프로덕트", "Product", "서비스"]):
                    continue
                company = job.get("company", {}).get("name", "")
                location = job.get("address", {}).get("location", "")
                job_id = job.get("id")
                jobs.append({
                    "company": company,
                    "position": position,
                    "location": location,
                    "link": f"https://www.wanted.co.kr/wd/{job_id}",
                })
        except Exception as e:
            print(f"[원티드 오류] {e}")
    return jobs


def fetch_jumpit():
    jobs = []
    for cat_id, label in JUMPIT_CATEGORIES:
        try:
            resp = requests.get(
                "https://api.jumpit.co.kr/api/positions",
                headers=JUMPIT_HEADERS,
                params={"sort": "rsp_rate", "jobCategory": cat_id, "page": 1},
                timeout=10,
            )
            resp.raise_for_status()
            result = resp.json().get("result", {})
            for job in result.get("positions", []):
                title = job.get("title", "")
                company = job.get("companyName", "")
                position_id = job.get("id")
                jobs.append({
                    "company": company,
                    "position": title,
                    "location": "",
                    "link": f"https://jumpit.saramin.co.kr/position/{position_id}",
                })
        except Exception as e:
            print(f"[점핏 오류] {e}")
    return jobs


def fetch_jobkorea():
    jobs = []
    seen = set()
    for keyword in JOBKOREA_KEYWORDS:
        try:
            resp = requests.get(
                "https://www.jobkorea.co.kr/Search/",
                headers=JOBKOREA_HEADERS,
                params={"stext": keyword, "tabType": "recruit"},
                timeout=10,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".list-default .list-item")[:10]:
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
                key = (company, title)
                if key not in seen:
                    seen.add(key)
                    jobs.append({
                        "company": company,
                        "position": title,
                        "location": "",
                        "link": href,
                    })
        except Exception as e:
            print(f"[잡코리아 오류] {e}")
    return jobs


def format_job_line(job):
    line = f"• **[{job['company']}]** {job['position']}"
    if job.get("location"):
        line += f" · {job['location']}"
    line += f"\n  {job['link']}"
    return line


def send_to_discord(wanted, jumpit, jobkorea):
    if not DISCORD_WEBHOOK_URL:
        print("DISCORD_WEBHOOK_URL 환경변수가 없습니다.")
        return

    today = datetime.now().strftime("%Y년 %m월 %d일")
    sections = []

    if wanted:
        lines = "\n".join(format_job_line(j) for j in wanted[:10])
        sections.append(f"🔵 **원티드** ({len(wanted)}개)\n{lines}")

    if jumpit:
        lines = "\n".join(format_job_line(j) for j in jumpit[:10])
        sections.append(f"🟢 **점핏** ({len(jumpit)}개)\n{lines}")

    if jobkorea:
        lines = "\n".join(format_job_line(j) for j in jobkorea[:10])
        sections.append(f"🔴 **잡코리아** ({len(jobkorea)}개)\n{lines}")

    if not sections:
        body = "오늘은 새로운 공고를 찾지 못했어요."
    else:
        body = "\n\n".join(sections)

    header = f"## 📋 {today} 디자이너 채용 공고\n\n"
    full_message = header + body

    # Discord 메시지 최대 2000자 → 청크 분할
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

    wanted = fetch_wanted()
    print(f"원티드: {len(wanted)}개")

    jumpit = fetch_jumpit()
    print(f"점핏: {len(jumpit)}개")

    jobkorea = fetch_jobkorea()
    print(f"잡코리아: {len(jobkorea)}개")

    send_to_discord(wanted, jumpit, jobkorea)
    print("완료!")
