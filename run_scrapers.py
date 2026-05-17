import json
from datetime import datetime, timezone, timedelta

from scrapers import snuh
from scrapers import severance


KST = timezone(timedelta(hours=9))


def main():
    all_jobs = []
    errors = {}

    try:
        snuh_jobs = snuh.collect(max_pages=5)
        all_jobs.extend(snuh_jobs)
        errors["snuh"] = None
    except Exception as e:
        errors["snuh"] = str(e)

    try:
        severance_jobs = severance.collect()
        all_jobs.extend(severance_jobs)
        errors["severance"] = None
    except Exception as e:
        errors["severance"] = str(e)

    output = {
        "updated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "total_count": len(all_jobs),
        "errors": errors,
        "jobs": all_jobs,
    }

    with open("jobs.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
