import re
import time
from datetime import datetime, timezone, timedelta

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://yuhs.recruiter.co.kr"
LIST_API_URL = "https://yuhs.recruiter.co.kr/app/jobnotice/list.json"
LIST_PAGE_URL = "https://yuhs.recruiter.co.kr/app/jobnotice/list"
DETAIL_PAGE_URL = "https://yuhs.recruiter.co.kr/app/jobnotice/view"

KST = timezone(timedelta(hours=9))

RECRUIT_CLASSES = ["신촌", "강남", "용인"]
TARGET_RECEIPT_STATE = "접수중"

TARGET_KEYWORDS = [
    "임상병리사",
    "진단검사의학팀",
    "진단검사의학과",
    "병리팀",
    "병리과",
]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def timestamp_ms_to_kst_string(ms: int | None) -> str:
    if not ms:
        return ""

    dt = datetime.fromtimestamp(ms / 1000, tz=KST)
    return dt.strftime("%Y.%m.%d %H:%M")


def format_apply_period(item: dict) -> str:
    start_ms = item.get("applyStartDate", {}).get("time")
    end_ms = item.get("applyEndDate", {}).get("time")

    start = timestamp_ms_to_kst_string(start_ms)
    end = timestamp_ms_to_kst_string(end_ms)

    if start and end:
        return f"{start} ~ {end}"

    return ""


def build_detail_url(jobnotice_sn: int | str) -> str:
    return f"{DETAIL_PAGE_URL}?jobnoticeSn={jobnotice_sn}&systemKindCode=MRS2"


def extract_employment_type(title: str) -> str:
    if "정규직전환조건" in title or "정규직 전환조건" in title:
        return "정규직 전환조건"

    if "정규직" in title:
        return "정규직"

    if "단기계약직" in title:
        return "단기계약직"

    if "계약직" in title:
        return "계약직"

    if "휴직대체" in title or "육아휴직" in title:
        return "휴직대체"

    return ""


def extract_department_from_title(title: str) -> str:
    department_keywords = [
        "진단검사의학팀",
        "진단검사의학과",
        "병리팀",
        "병리과",
        "분자유전파트",
    ]

    for keyword in department_keywords:
        if keyword in title:
            return keyword

    return ""


def is_target_notice(item: dict) -> bool:
    title = item.get("jobnoticeName", "")
    receipt_state = item.get("receiptState", "")

    if receipt_state != TARGET_RECEIPT_STATE:
        return False

    return any(keyword in title for keyword in TARGET_KEYWORDS)


def fetch_list_page(
    session: requests.Session,
    recruit_class_name: str,
    current_page: int,
    page_size: int = 10,
) -> dict:
    payload = {
        "recruitClassSn": "",
        "recruitClassName": recruit_class_name,
        "jobnoticeStateCode": "10",
        "pageSize": str(page_size),
        "searchByNameOnly": "true",
        "currentPage": str(current_page),
        "keyword": "",
    }

    response = session.post(
        LIST_API_URL,
        data=payload,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Origin": BASE_URL,
            "Referer": LIST_PAGE_URL,
            "X-Requested-With": "XMLHttpRequest",
        },
    )

    response.raise_for_status()
    return response.json()


def fetch_detail_info(session: requests.Session, jobnotice_sn: int | str, title: str) -> dict:
    detail_url = build_detail_url(jobnotice_sn)

    response = session.get(
        detail_url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0 Safari/537.36"
            ),
            "Referer": LIST_PAGE_URL,
        },
    )

    response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, "lxml")

    lines = [
        normalize_text(line)
        for line in soup.get_text("\n", strip=True).splitlines()
        if normalize_text(line)
    ]

    full_text = "\n".join(lines)

    department = extract_department_from_title(title)
    for keyword in ["진단검사의학팀", "진단검사의학과", "병리팀", "병리과", "분자유전파트"]:
        if keyword in full_text:
            department = keyword
            break

    headcount = ""
    headcount_patterns = [
        r"모집인원\s*[:：]?\s*(\d+)\s*명",
        r"채용인원\s*[:：]?\s*(\d+)\s*명",
        r"(\d+)\s*명",
    ]

    for pattern in headcount_patterns:
        match = re.search(pattern, full_text)
        if match:
            headcount = f"{match.group(1)}명"
            break

    qualification = ""
    if "임상병리사" in full_text:
        if "면허" in full_text:
            qualification = "임상병리사 면허"
        else:
            qualification = "임상병리사"

    contract_period = ""
    contract_patterns = [
        r"계약기간\s*[:：]?\s*([^\n]+)",
        r"근무기간\s*[:：]?\s*([^\n]+)",
        r"임용기간\s*[:：]?\s*([^\n]+)",
    ]

    for pattern in contract_patterns:
        match = re.search(pattern, full_text)
        if match:
            contract_period = normalize_text(match.group(1))
            break

    return {
        "department": department,
        "headcount": headcount,
        "qualification": qualification,
        "contract_period": contract_period,
    }


def convert_item_to_job(session: requests.Session, item: dict) -> dict:
    title = item.get("jobnoticeName", "")
    jobnotice_sn = item.get("jobnoticeSn")
    recruit_class_name = item.get("recruitClassName", "")

    detail_url = build_detail_url(jobnotice_sn)

    detail_info = {
        "department": extract_department_from_title(title),
        "headcount": "",
        "qualification": "임상병리사" if "임상병리사" in title else "",
        "contract_period": "",
    }

    try:
        detail_info.update(fetch_detail_info(session, jobnotice_sn, title))
    except Exception as e:
        detail_info["detail_error"] = str(e)

    return {
        "hospital": f"세브란스병원-{recruit_class_name}",
        "source": "YUHS Recruiter",
        "title": title,
        "status": item.get("receiptState", ""),
        "career_type": item.get("recruitTypeName", ""),
        "application_period": format_apply_period(item),
        "deadline_count": item.get("deadlineCount"),
        "positions": [
            {
                "employment_type": extract_employment_type(title),
                "department": detail_info.get("department", ""),
                "headcount": detail_info.get("headcount", ""),
                "qualification": detail_info.get("qualification", ""),
                "contract_period": detail_info.get("contract_period", ""),
            }
        ],
        "detail_url": detail_url,
        "jobnotice_sn": jobnotice_sn,
        "scraped_at": datetime.now(KST).isoformat(timespec="seconds"),
    }


def collect_by_recruit_class(session: requests.Session, recruit_class_name: str) -> list[dict]:
    results = []

    first_data = fetch_list_page(
        session=session,
        recruit_class_name=recruit_class_name,
        current_page=1,
    )

    page_util = first_data.get("pageUtil", {})
    last_page = int(page_util.get("lastPage", 1))

    for current_page in range(1, last_page + 1):
        if current_page == 1:
            data = first_data
        else:
            data = fetch_list_page(
                session=session,
                recruit_class_name=recruit_class_name,
                current_page=current_page,
            )

        for item in data.get("list", []):
            if not is_target_notice(item):
                continue

            results.append(convert_item_to_job(session, item))

        time.sleep(0.4)

    return results


def collect() -> list[dict]:
    session = requests.Session()
    all_results = []

    for recruit_class_name in RECRUIT_CLASSES:
        all_results.extend(collect_by_recruit_class(session, recruit_class_name))

    deduped = {}

    for job in all_results:
        jobnotice_sn = job.get("jobnotice_sn")
        if jobnotice_sn:
            deduped[jobnotice_sn] = job

    return list(deduped.values())
