"""Collect software jobs from public job sites (no logins) into jobs.xlsx.

Run:  python jobs.py
Re-running only appends NEW jobs; your Status column edits are kept.
"""
import html
import json
import re
import shutil
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.worksheet.datavalidation import DataValidation

import filters

# ---------------- config ----------------
OUT = Path(__file__).with_name("jobs.xlsx")
KEYWORDS = ["angular developer", "full stack developer", "java developer",
            "software engineer", "junior software developer", "graduate software engineer"]
SEEK_PAGES = 3                      # 22 jobs per page per keyword
LINKEDIN_PAGES = 2                  # 25 jobs per page per keyword
HATCH_LEVELS = ["intern", "graduate", "junior", "mid-level"]
HATCH_CITIES = ["", "sydney", "melbourne", "brisbane", "perth", "adelaide", "canberra", "hobart"]
SKIP_SENIOR = True                  # drop Senior/Lead titles, EXCEPT ones that mention Angular
SENIOR_EXCEPTION = re.compile(r"angular", re.I)
MAX_AGE_DAYS = 30                   # Seek/LinkedIn only; ignore older ads
DELAY = 1.5                         # seconds between requests (be polite, avoid blocks)

SENIOR = re.compile(r"senior|snr|sr\.|lead\b|principal|staff|head of|manager|director|architect", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
COLS = ["Date found", "Company", "Title", "Level", "Location", "Source", "Search",
        "Visa note", "URL", "Status", "Posted"]


def fetch(url):
    time.sleep(DELAY)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"   ! {url[:90]}... {e}")
        return ""


def level_of(title):
    t = title.lower()
    if re.search(r"intern|cadet|trainee", t):
        return "Intern"
    if re.search(r"grad", t):
        return "Grad"
    if re.search(r"junior|entry|associate|jr\b", t):
        return "Junior"
    if SENIOR.search(t):
        return "Senior"
    return "Mid"


def visa_note(text):
    return ""  # real visa check happens later on the full ad text (filters.visa_check)


def page_text(raw, limit=20000):
    raw = re.sub(r"<(script|style|svg|noscript)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))[:limit]


def div_text(raw, marker, limit=20000):
    """Text of the (balanced) <div> that carries `marker`."""
    i = raw.find(marker)
    if i < 0:
        return ""
    start = raw.rfind("<div", 0, i)
    depth, pos = 0, start
    for m in re.finditer(r"</?div\b", raw[start:]):
        depth += -1 if m.group(0) == "</div" else 1
        pos = start + m.end()
        if depth == 0:
            break
    return page_text(raw[start:pos], limit)


def full_text(job):
    """Fetch the whole job description (needed to judge relevance and visa wording)."""
    src, url = job["Source"], job["URL"]
    if src == "Seek":
        return div_text(fetch(url), 'data-automation="jobAdDetails"')
    if src == "LinkedIn":
        m = re.search(r"(\d{6,})(?:\?|$)", url)
        return page_text(fetch(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}")) if m else ""
    if src in ("Hatch", "BuiltIn Sydney"):
        return page_text(fetch(url))
    if src == "Company site" and "smartrecruiters" in url:
        m = re.search(r"smartrecruiters\.com/([^/]+)/(\d+)", url)
        try:
            d = json.loads(fetch(f"https://api.smartrecruiters.com/v1/companies/{m.group(1)}/postings/{m.group(2)}"))
            return page_text(" ".join(v.get("text", "") for v in d["jobAd"]["sections"].values()))
        except Exception:
            return ""
    return job.get("_text", "")


# ---------------- sources ----------------
def seek():
    out = []
    for kw in KEYWORDS:
        for page in range(1, SEEK_PAGES + 1):
            q = urllib.parse.urlencode({"siteKey": "AU-Main", "keywords": kw, "where": "All Australia",
                                        "page": page, "pageSize": 22, "dateRange": MAX_AGE_DAYS,
                                        "sortmode": "ListedDate"})
            raw = fetch("https://www.seek.com.au/api/jobsearch/v5/search?" + q)
            try:
                data = json.loads(raw)["data"]
            except Exception:
                break
            if not data:
                break
            for d in data:
                out.append({
                    "Company": d.get("companyName") or d.get("advertiser", {}).get("description", ""),
                    "Title": d["title"],
                    "Location": ", ".join(l["label"] for l in d.get("locations", [])[:1]),
                    "Source": "Seek", "Search": kw,
                    "Visa note": visa_note(d.get("teaser", "") + " " + " ".join(d.get("bulletPoints", []))),
                    "_text": d.get("teaser", "") + " " + " ".join(d.get("bulletPoints", [])),
                    "URL": f"https://www.seek.com.au/job/{d['id']}",
                    "Posted": d.get("listingDate", "")[:10],
                })
        print(f"   seek '{kw}': {len(out)} so far")
    return out


def linkedin():
    out = []
    for kw in KEYWORDS:
        for page in range(LINKEDIN_PAGES):
            q = urllib.parse.urlencode({"keywords": kw, "location": "Australia", "f_TPR": "r2592000",
                                        "start": page * 25})
            h = fetch("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + q)
            cards = re.split(r'<li>', h)[1:]
            if not cards:
                break
            for c in cards:
                u = re.search(r'href="(https://[a-z.]*linkedin\.com/jobs/view/[^"?]+)', c)
                t = re.search(r'base-search-card__title">\s*(.*?)\s*</h3>', c, re.S)
                co = re.search(r'base-search-card__subtitle">.*?>\s*(.*?)\s*</a>', c, re.S) or \
                    re.search(r'base-search-card__subtitle">\s*(.*?)\s*</h4>', c, re.S)
                lo = re.search(r'job-search-card__location">\s*(.*?)\s*</span>', c, re.S)
                dt = re.search(r'datetime="([\d-]+)"', c)
                if not (u and t):
                    continue
                out.append({"Company": html.unescape(co.group(1)) if co else "",
                            "Title": html.unescape(t.group(1)),
                            "Location": html.unescape(lo.group(1)) if lo else "",
                            "Source": "LinkedIn", "Search": kw, "Visa note": "",
                            "URL": u.group(1), "Posted": dt.group(1) if dt else ""})
        print(f"   linkedin '{kw}': {len(out)} so far")
    return out


def hatch():
    out, seen = [], set()
    for lvl in HATCH_LEVELS:
        for city in HATCH_CITIES:
            h = fetch(f"https://hatch.team/jobs/software-engineering/{lvl}" + (f"/{city}" if city else ""))
            for path in dict.fromkeys(re.findall(r'href="(/job/[^"?]+)', h)):
                if path in seen:
                    continue
                seen.add(path)
                j = fetch("https://hatch.team" + path)
                m = re.search(r'<script type="application/ld\+json">(\{"@context".*?"@type":"JobPosting".*?)</script>',
                              j, re.S)
                if not m:
                    continue
                try:
                    d = json.loads(m.group(1))
                except Exception:
                    continue
                a = d.get("jobLocation", {}).get("address", {})
                loc = ", ".join(x for x in [a.get("addressLocality"), a.get("addressRegion")] if x)
                desc = re.sub(r"<[^>]+>", " ", d.get("description", ""))
                out.append({"Company": d.get("hiringOrganization", {}).get("name", ""),
                            "Title": d.get("title", ""), "Location": loc or "Australia",
                            "Source": "Hatch", "Search": lvl, "Visa note": visa_note(desc), "_text": desc,
                            "URL": "https://hatch.team" + path,
                            "Posted": d.get("datePosted", "")[:10]})
        print(f"   hatch {lvl}: {len(out)} so far")
    return out


def builtin():
    out = []
    for kw in ["angular", "full stack", "java", "software engineer", "junior developer", "graduate"]:
        for page in (1, 2):
            h = fetch("https://builtinsydney.au/jobs?" + urllib.parse.urlencode({"search": kw, "page": page}))
            cards = h.split('data-id="company-title"')[1:]
            if not cards:
                break
            for c in cards:
                u = re.search(r'data-id="job-card-title"[^>]*href="(/job/[^"]+)"', c) or                     re.search(r'href="(/job/[^"]+)"[^>]*data-id="job-card-title"', c)
                t = re.search(r'data-id="job-card-title"[^>]*>(.*?)</a>', c, re.S)
                co = re.search(r'<span>(.*?)</span>', c, re.S)
                txt = re.sub(r"<[^>]+>", "|", c[:6000])
                lo = re.search(r"([A-Za-z .]+(?:, [A-Za-z .]+)*, AUS|\d+ Locations)", txt)
                if not (u and t):
                    continue
                out.append({"Company": html.unescape(co.group(1)) if co else "",
                            "Title": html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip(),
                            "Location": lo.group(1).strip() if lo else "Australia",
                            "Source": "BuiltIn Sydney", "Search": kw, "Visa note": "", "_text": re.sub(r"\s+", " ", txt[:1200]),
                            "URL": "https://builtinsydney.au" + u.group(1), "Posted": ""})
        print(f"   builtin '{kw}': {len(out)} so far")
    return out


def employmenthero():
    out, seen = [], set()
    for slug in ["software-developer", "it", "engineer", "internship"]:
        for page in (1, 2):
            h = fetch(f"https://employmenthero.com/jobs/{slug}/?page={page}")
            for u in dict.fromkeys(re.findall(r'href="(https://employmenthero\.com/jobs/position/[^"]+)"', h)):
                if u in seen:
                    continue
                seen.add(u)
                j = fetch(u)
                for x in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', j, re.S):
                    if "JobPosting" not in x:
                        continue
                    try:
                        d = json.loads(x)
                    except Exception:
                        break
                    loc = d.get("jobLocation") or {}
                    loc = loc[0] if isinstance(loc, list) and loc else loc
                    a = loc.get("address", {}) if isinstance(loc, dict) else {}
                    desc = re.sub(r"<[^>]+>", " ", html.unescape(d.get("description", "")))
                    out.append({"Company": (d.get("hiringOrganization") or {}).get("name", ""),
                                "Title": html.unescape(d.get("title", "")),
                                "Location": ", ".join(v for v in [a.get("addressLocality"), a.get("addressRegion")] if v) or "Australia",
                                "Source": "Employment Hero", "Search": slug, "Visa note": visa_note(desc),
                                "_text": desc, "URL": u, "Posted": str(d.get("datePosted", ""))[:10]})
                    break
        print(f"   employment hero '{slug}': {len(out)} so far")
    return out


AU_LOC = re.compile(r"australia|sydney|melbourne|brisbane|perth|adelaide|canberra|hobart|darwin|gold coast|"
                    r"newcastle|wollongong|\bnsw\b|\bvic\b|\bqld\b|\bau\b|\bwa\b|\bact\b", re.I)
# (ats, slug, display name) - add more companies here
COMPANIES = [("ashby", "airwallex", "Airwallex"), ("ashby", "xero", "Xero"), ("ashby", "zip", "Zip"),
             ("ashby", "siteminder", "SiteMinder"), ("ashby", "assembly", "Assembly"),
             ("ashby", "snowflake", "Snowflake"),
             ("greenhouse", "cultureamp", "Culture Amp"), ("greenhouse", "buildkite", "Buildkite"),
             ("greenhouse", "thoughtworks", "Thoughtworks"), ("greenhouse", "pushpay", "Pushpay"),
             ("greenhouse", "block", "Block"), ("greenhouse", "cloudflare", "Cloudflare"),
             ("greenhouse", "databricks", "Databricks"), ("greenhouse", "mongodb", "MongoDB"),
             ("greenhouse", "okta", "Okta"), ("greenhouse", "elastic", "Elastic"),
             ("greenhouse", "gitlab", "GitLab"), ("greenhouse", "twilio", "Twilio"),
             ("greenhouse", "pagerduty", "PagerDuty"),
             ("lever", "deputy", "Deputy"), ("lever", "immutable", "Immutable"),
             ("lever", "mable", "Mable"), ("lever", "megaport", "Megaport"), ("lever", "pexa", "PEXA"),
             ("smartrecruiters", "Canva", "Canva"), ("smartrecruiters", "carsales", "carsales"),
             ("smartrecruiters", "nearmap", "Nearmap"), ("smartrecruiters", "nextdc", "NEXTDC"),
             ("smartrecruiters", "propertyme", "PropertyMe"), ("smartrecruiters", "coinjar", "CoinJar")]


def companies():
    out = []
    for ats, slug, name in COMPANIES:
        rows = []  # (title, location, url, posted)
        if ats == "greenhouse":
            d = json.loads(fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs") or '{"jobs":[]}')
            rows = [(x["title"], (x.get("location") or {}).get("name", ""), x["absolute_url"],
                     x.get("updated_at", "")[:10]) for x in d.get("jobs", [])]
        elif ats == "lever":
            d = json.loads(fetch(f"https://api.lever.co/v0/postings/{slug}?mode=json") or "[]")
            rows = [(x["text"], (x.get("categories") or {}).get("location", ""), x["hostedUrl"],
                     time.strftime("%Y-%m-%d", time.gmtime(x.get("createdAt", 0) / 1000))) for x in d]
        elif ats == "ashby":
            d = json.loads(fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}") or '{"jobs":[]}')
            rows = [(x["title"], " / ".join(l for l in [x.get("location", "")] + [
                        l.get("location", "") if isinstance(l, dict) else str(l)
                        for l in x.get("secondaryLocations", [])] if AU_LOC.search(l or "")),
                     x["jobUrl"], str(x.get("publishedAt", ""))[:10])
                    for x in d.get("jobs", []) if x.get("isListed", True)]
        elif ats == "smartrecruiters":
            d = json.loads(fetch(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country=au&limit=100")
                           or '{"content":[]}')
            rows = [(x["name"], ", ".join(v for v in [x.get("location", {}).get("city"),
                                                      x.get("location", {}).get("region")] if v) or "Australia",
                     f"https://jobs.smartrecruiters.com/{slug}/{x['id']}", str(x.get("releasedDate", ""))[:10])
                    for x in d.get("content", [])]
        for title, loc, url, posted in rows:
            if ats != "smartrecruiters" and not AU_LOC.search(loc or ""):
                continue
            out.append({"Company": name, "Title": title, "Location": loc, "Source": "Company site",
                        "Search": ats, "Visa note": "", "URL": url, "Posted": posted})
        print(f"   {name}: {len(out)} so far")
    return out


SOURCES = {"Seek": seek, "LinkedIn": linkedin, "Hatch": hatch, "BuiltIn Sydney": builtin,
           "Employment Hero": employmenthero, "Company sites": companies}


# ---------------- excel ----------------
def job_key(url):
    b = re.search(r"builtinsydney\.au/job/[^/]+/(\d+)", url)
    if b:
        return "bi" + b.group(1)
    if any(h in url for h in ("employmenthero.com", "smartrecruiters", "greenhouse", "lever.co", "ashbyhq")):
        return url.split("?")[0].rstrip("/")
    m = re.search(r"/job/(\d+)", url) or re.search(r"-(\d{6,})$", url.split("?")[0]) or \
        re.search(r"(job_\w+)", url)
    return m.group(1) if m else url


def load_existing():
    if not OUT.exists():
        return None, set()
    wb = load_workbook(OUT)
    ws = wb.active
    keys = {job_key(str(r[COLS.index("URL")])) for r in ws.iter_rows(min_row=2, values_only=True)
            if r[COLS.index("URL")]}
    return wb, keys


def save(wb, quiet=False):
    """Save; if jobs.xlsx is open in Excel (locked), fall back to a side file so nothing is lost."""
    try:
        wb.save(OUT)
    except PermissionError:
        if quiet:
            return
        alt = OUT.with_name("jobs_new.xlsx")
        wb.save(alt)
        print(f"! {OUT.name} is open in Excel, so results were saved to {alt.name} instead. "
              f"Close Excel and rename it.")


def main():
    if OUT.with_name("~$" + OUT.name).exists():
        print(f"{OUT.name} is open in Excel. Save and close it first, so your Status edits aren't lost. Nothing was changed.")
        return
    if OUT.exists():  # keep a copy of every previous version
        backups = OUT.parent / "backups"
        backups.mkdir(exist_ok=True)
        shutil.copy2(OUT, backups / f"jobs_{time.strftime('%Y%m%d_%H%M%S')}.xlsx")
    wb, known = load_existing()
    if wb is None:
        wb = Workbook()
        ws = wb.active
        ws.title = "Jobs"
        ws.append(COLS)
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for col, w in zip("ABCDEFGHIJK", [12, 28, 48, 9, 26, 10, 24, 28, 60, 12, 12]):
            ws.column_dimensions[col].width = w
        dv = DataValidation(type="list", formula1='"Ready,Applied,Incomplete,Skip,Interview,Rejected"')
        ws.add_data_validation(dv)
        dv.add("J2:J5000")
    ws = wb["Jobs"] if "Jobs" in wb.sheetnames else wb.active

    # rebuild: keep rows you've already acted on (Status != Ready); 'Ready' rows are re-checked below
    status_col = COLS.index("Status") + 1
    for r in range(ws.max_row, 1, -1):
        if str(ws.cell(r, status_col).value or "Ready") == "Ready":
            ws.delete_rows(r)
    known = {job_key(str(ws.cell(r, COLS.index("URL") + 1).value)) for r in range(2, ws.max_row + 1)}
    if "Excluded" in wb.sheetnames:  # don't re-read ads that were already rejected on an earlier run
        known |= {job_key(str(r[5])) for r in wb["Excluded"].iter_rows(min_row=2, values_only=True) if r[5]}

    new = []
    for name, fn in SOURCES.items():
        print(f"[{name}]")
        try:
            new += fn()
        except Exception as e:
            print(f"   ! {name} failed: {e}")

    # 1) cheap title filter, dedupe
    cands, seen = [], set(known)
    for j in new:
        k = job_key(j["URL"])
        if k in seen:
            continue
        seen.add(k)
        j["Level"] = level_of(j["Title"])
        verdict = filters.title_verdict(j["Title"])
        if verdict == "reject":
            continue
        if j["Level"] == "Senior" and not re.search(r"angular", j["Title"] + " " + j.get("_text", ""), re.I):
            continue  # senior roles are only wanted when they look like Angular roles
        j["_verdict"] = verdict
        cands.append(j)
    print(f"\n{len(cands)} candidates after title filter; reading full descriptions "
          f"(~{len(cands) * DELAY / 60:.0f} min)...")

    # 2) read the full ad, then judge relevance + visa wording
    ex = wb["Excluded"] if "Excluded" in wb.sheetnames else None
    if ex is None:
        ex = wb.create_sheet("Excluded")
        ex.append(COLS[:3] + ["Source", "Reason", "URL"])
        for c in ex[1]:
            c.font = Font(bold=True)
    added, dropped, today = 0, 0, date.today().strftime("%d/%m/%Y")
    for n, j in enumerate(cands, 1):
        text = full_text(j)
        reason, vnote = "", ""
        if j["Level"] == "Senior" and not filters.senior_ok(j["Title"], text):
            reason = "senior role, not clearly Angular"
        elif j["_verdict"] == "maybe" and not filters.relevant_by_text(text):
            reason = "not a software role (by description)"
        else:
            status, vnote = filters.visa_check(text) if text else ("ok", "ad text not read - check visa wording")
            if status == "block":
                reason = vnote
        if reason:
            ex.append([j["Date found"] if "Date found" in j else today, j["Company"], j["Title"], j["Source"], reason, j["URL"]])
            dropped += 1
            continue
        j["Visa note"] = vnote
        j["Date found"], j["Status"] = today, "Ready"
        ws.append([j.get(c, "") for c in COLS])
        cell = ws.cell(row=ws.max_row, column=COLS.index("URL") + 1)
        cell.hyperlink = j["URL"]
        cell.font = Font(color="0563C1", underline="single")
        added += 1
        if n % 25 == 0:
            print(f"   {n}/{len(cands)} read, {added} kept, {dropped} dropped")
            save(wb, quiet=True)
    save(wb)
    print(f"\nDone. {added} new jobs added, {dropped} excluded (see 'Excluded' sheet) -> {OUT}")


if __name__ == "__main__":
    main()
