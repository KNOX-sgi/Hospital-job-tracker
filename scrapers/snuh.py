import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://recruit.snuh.org"
LIST_URL = "https://recruit.snuh.org/joining/recruit/list.do"

TARGET_TITLE = "서울대학교병원 블라인드 직원채용 (대체근로자) 공고 (장애인 특별우대)"
TARGET_STATUS = "공고"
TARGET_DEPARTMENTS = ["진단검사의학과", "병리과"]
TARGET_LICENSE = "임상병리사"

KST = timezone(timedelta(hours=9))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def get_soup(session: requests.Session, url: str, params: dict | None = None) -> BeautifulSoup:
    response = session.get(
        url,
        params=params,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            )
        },
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding
    return BeautifulSoup(response.text, "lxml")


def extract_recruit_id_from_row(row) -> str | None:
    html = str(row)

    patterns = [
        r"recruit_id=(\d+)",
        r"recruit_id['\"]?\s*[:=]\s*['\"]?(\d+)",
        r"recruitId['\"]?\s*[:=]\s*['\"]?(\d+)",
        r"recruView\.do\?recruit_id=(\d+)",
        r"view\.do\?[^'\"]*recruit_id=(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)

    return None


def parse_list_page(session: requests.Session, page_index: int) -> list[dict]:
    soup = get_soup(
        session,
        LIST_URL,
        params={
            "pageIndex": page_index,
            "career_cd": "",
            "spt_field": "",
            "searchKey": "",
            "searchWord": "",
        },
    )

    candidates = []

    for row in soup.select("tr"):
        cells = [normalize_text(td.get_text(" ", strip=True)) for td in row.select("td")]

        if len(cells) < 5:
            continue

        number, title, recruit_period, career_type, status = cells[:5]

        if title != TARGET_TITLE:
            continue

        if status != TARGET_STATUS:
            continue

        recruit_id = extract_recruit_id_from_row(row)

        detail_url = None

        if recruit_id:
            detail_url = f"{BASE_URL}/joining/recruit/view.do?notice_type=E&recruit_id={recruit_id}"
        else:
            link = row.find("a", href=True)
            if link:
                detail_url = urljoin(BASE_URL, link["href"])

        candidates.append(
            {
                "number": number,
                "title": title,
                "list_recruit_period": recruit_period,
                "career_type": career_type,
                "status": status,
                "detail_url": detail_url,
                "page_index": page_index,
            }
        )

    return candidates


def extract_application_period(text: str, fallback: str = "") -> str:
    patterns = [
        r"채용공고 및 원서접수\s*([0-9]{4}\.[0-9]{2}\.[0-9]{2}.*?~.*?[0-9]{4}\.[0-9]{2}\.[0-9]{2}.*?[0-9]{2}:[0-9]{2})",
        r"지원접수기간\s*[:：]?\s*([0-9]{4}[-./][0-9]{2}[-./][0-9]{2}.*?~.*?[0-9]{4}[-./][0-9]{2}[-./][0-9]{2})",
        r"모집기간\s*[:：]?\s*([0-9]{4}[-./][0-9]{2}[-./][0-9]{2}.*?~.*?[0-9]{4}[-./][0-9]{2}[-./][0-9]{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.S)
        if match:
            return normalize_text(match.group(1))

    return fallback


def get_health_job_block(lines: list[str]) -> list[str]:
    start = None

    for i in range(len(lines) - 1):
        if lines[i] == "촉탁" and lines[i + 1] == "보건직":
            start = i + 2
            break

    if start is None:
        return []

    end = len(lines)

    for i in range(start, len(lines) - 1):
        if lines[i] == "촉탁" and lines[i + 1] != "보건직":
            end = i
            break

        if lines[i] in ["단시간", "무기계약직"]:
            end = i
            break

        if "전형방법" in lines[i] or "전형일정" in lines[i]:
            end = i
            break

    return lines[start:end]


def parse_detail_page(session: requests.Session, item: dict) -> dict | None:
    detail_url = item.get("detail_url")

    if not detail_url:
        return None

    soup = get_soup(session, detail_url)

    raw_lines = [
        normalize_text(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if normalize_text(line)
    ]

    full_text = "\n".join(raw_lines)
    application_period = extract_application_period(
        full_text,
        fallback=item.get("list_recruit_period", ""),
    )

    health_lines = get_health_job_block(raw_lines)

    positions = []

    for i, line in enumerate(health_lines):
        department = None

        for target_department in TARGET_DEPARTMENTS:
            if line.startswith(target_department):
                department = line
                break

        if not department:
            continue

        window = health_lines[i : i + 12]
        window_text = "\n".join(window)

        if TARGET_LICENSE not in window_text:
            continue

        count_match = re.search(r"(\d+)\s*명", window_text)
        headcount = f"{count_match.group(1)}명" if count_match else ""

        contract_match = re.search(
            r"약\s*\d+\s*개월(?:\s*\([^)]+\))?",
            normalize_text(window_text),
        )
        contract_period = contract_match.group(0) if contract_match else ""

        positions.append(
            {
                "employment_type": "촉탁보건직",
                "department": department,
                "headcount": headcount,
                "qualification": TARGET_LICENSE,
                "contract_period": contract_period,
            }
        )

    if not positions:
        return None

    return {
        "hospital": "서울대학교병원",
        "title": item["title"],
        "status": item["status"],
        "career_type": item["career_type"],
        "application_period": application_period,
        "positions": positions,
        "detail_url": detail_url,
        "source_page": item["page_index"],
        "scraped_at": datetime.now(KST).isoformat(timespec="seconds"),
    }


def collect(max_pages: int = 5) -> list[dict]:
    session = requests.Session()
    results = []

    for page_index in range(1, max_pages + 1):
        list_items = parse_list_page(session, page_index)

        for item in list_items:
            parsed = parse_detail_page(session, item)
            if parsed:
                results.append(parsed)

        time.sleep(0.8)

    return results
