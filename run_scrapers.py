import json
from datetime import datetime, timezone, timedelta

from scrapers import snuh


KST = timezone(timedelta(hours=9))


def main():
    all_jobs = []

    try:
        snuh_jobs = snuh.collect(max_pages=5)
        all_jobs.extend(snuh_jobs)
        snuh_error = None
    except Exception as e:
        snuh_error = str(e)

    output = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "total_count": len(all_jobs),
        "errors": {
            "snuh": snuh_error,
        },
        "jobs": all_jobs,
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
