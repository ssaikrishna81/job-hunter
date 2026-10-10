"""Relevance + visa filters for jobs.py (kept separate so they can be tested on their own)."""
import re

# ---- title rules ----
TITLE_BAD = re.compile(
    r"sales|pre.?sales|solutions? (engineer|architect|consultant)|customer success|support|help ?desk|service desk|"
    r"desktop|technician|mechanical|civil|electrical|structural|chemical|hardware|network|electronic|embedded|"
    r"firmware|pcb|process engineer|production|site engineer|field|service engineer|audit|account|recruit|"
    r"nurse|teacher|manager|\blead\b|principal|head of|director|architect|staff engineer|business analyst|"
    r"data analyst|scientist|marketing|designer|graphic|ux\b|hvac|mining|geotech|environmental|quantity|"
    r"construction|estimator|procurement|administrator|coordinator|specialist|consultant (?!.*(software|developer))",
    re.I)
TITLE_STRONG = re.compile(
    r"software|developer|programmer|full.?stack|front.?end|back.?end|web (app|dev|eng)|angular|\bjava\b|"
    r"javascript|typescript|\breact\b|\bnode|python|\.net|\bc#|golang|devops|\bsre\b|site reliability|"
    r"cloud (engineer|developer)|platform engineer|data engineer|machine learning|\bml\b|\bai\b (engineer|developer)|"
    r"application (developer|engineer)|mobile (dev|eng)|\bios\b|android|test automation|\bsdet\b|"
    r"quality (assurance )?engineer|\bqa\b (engineer|automation)|technology graduate|tech graduate|"
    r"graduate (developer|programmer|software|technolog)|digital (engineer|developer)|integration (engineer|developer)|"
    r"api\b|systems? (developer|engineer)|analyst programmer", re.I)
TITLE_GENERIC = re.compile(r"engineer|developer|graduate|program|technolog|trainee|cadet|intern|associate|analyst", re.I)

SOFT_TERMS = ["software", "programming", "javascript", "typescript", "java", "python", "react", "angular",
              "api", "sql", "aws", "azure", "cloud", "coding", "github", "git", "devops", "ci/cd",
              "web application", "frontend", "front-end", "backend", "back-end", "full stack", "full-stack",
              "microservice", "database", "agile", "scrum", "c#", ".net", "node"]
NEG_DOMAIN = re.compile(
    r"construction|civil|structural|mechanical|hvac|\bplc\b|scada|building management|electrical|substation|"
    r"geotechnical|mining|drilling|surveying|chemical|manufacturing|fire (and|&) security|controls? systems?|"
    r"site (safety|supervis)|commissioning|piping|water treatment|rail (signal|infra)|hydraulic", re.I)


def title_verdict(title):
    """'reject' | 'accept' | 'maybe' (maybe = decide after reading the description)."""
    if TITLE_BAD.search(title):
        return "reject"
    if TITLE_STRONG.search(title):
        return "accept"
    if TITLE_GENERIC.search(title):
        return "maybe"
    return "reject"


def relevant_by_text(text):
    low = (text or "").lower()
    hits = sum(1 for t in SOFT_TERMS if re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", low))
    neg = len(NEG_DOMAIN.findall(text or ""))
    return hits >= 4 and neg < 3


def senior_ok(title, text):
    """Senior roles only if they are clearly Angular roles."""
    return bool(re.search(r"angular", title, re.I)) or len(re.findall(r"angular", text or "", re.I)) >= 3


# ---- visa rules ----
CIT = re.compile(
    r"australian citizen|citizenship|citizens? ?(/|or|and|,) ?(permanent|PR\b)|\bPR ?(/|or|and) ?citizen|"
    r"permanent residen|\bPR (holder|status)|australian ?(/|or) ?(nz|new zealand) citizen|"
    r"(nz|new zealand) citizen|security clearance|\bNV ?[12]\b|baseline clearance|\bAGSVA\b|"
    r"defence clearance|government clearance|police clearance and (citizen)|clearance", re.I)
INCLUSIVE = re.compile(
    r"(valid|appropriate|relevant|current|eligible|temporary|work|working|student|graduate|post.?study)[ -]*(work )?visa|"
    r"visa holder|work(ing)? rights|right to work|eligible to work|entitle[d]? to work|subclass|\b485\b|"
    r"hold (a )?(visa|work)|visa that allows|on a visa", re.I)
SOFT = re.compile(r"prefer|encourag|desirable|advantage|beneficial|welcome|nice to have|bonus|equal opportunit|"
                  r"regardless|not required|no clearance|do not require|doesn.t require|not a requirement|"
                  r"first nations|aboriginal|indigenous|diversity", re.I)
NEEDS_RIGHTS = re.compile(r"full (work(ing)? rights|working rights)|unrestricted (work|working)|"
                          r"right to work in australia|work rights? in australia|rights? to work", re.I)


def split_sentences(text):
    text = re.sub(r"\s+", " ", text or "")
    return [s.strip() for s in re.split(r"(?<=[.!?;:•·])\s+|\s[-–—]\s|\s\|\s", text) if s.strip()]


def visa_check(text):
    """Return (status, note). status: 'block' = PR/citizen strictly required, 'check' = mentions
    citizen/PR *and* allows visa holders (or asks for work rights), 'ok' = nothing found."""
    sents = split_sentences(text)
    check_note = ""
    for i, s in enumerate(sents):
        if not CIT.search(s):
            continue
        if SOFT.search(s):
            continue
        window = " ".join(sents[max(0, i - 1):i + 2])
        if re.search(r"clearance|\bNV ?[12]\b", s, re.I):
            return "block", "clearance: " + s[:110]
        if INCLUSIVE.search(window):
            check_note = check_note or ("citizen/PR + visa OK?: " + s[:110])
            continue
        return "block", "citizen/PR only: " + s[:110]
    if check_note:
        return "check", check_note
    m = NEEDS_RIGHTS.search(text or "")
    if m:
        return "check", "asks for work rights: '" + m.group(0) + "'"
    return "ok", ""


if __name__ == "__main__":
    tests = [
        ("You must be an Australian citizen or permanent resident to apply.", "block"),
        ("Applicants must hold Australian citizenship. Baseline clearance is required.", "block"),
        ("Must be an Australian citizen or PR, or hold a valid work visa.", "check"),
        ("Australian citizens, permanent residents and visa holders with full work rights may apply.", "check"),
        ("You must have full working rights in Australia.", "check"),
        ("Australian citizens and PR are encouraged to apply.", "ok"),
        ("We are a good corporate citizen and love our community.", "ok"),
        ("Ability to obtain NV1 security clearance.", "block"),
        ("Visa sponsorship is not available. Candidates must be Australian citizens or permanent residents.", "block"),
        ("Open to all candidates with valid work rights in Australia.", "check"),
        ("Build web apps with Angular and Java.", "ok"),
    ]
    for t, want in tests:
        got = visa_check(t)[0]
        print("OK " if got == want else "BAD", got, "|", t)
    for t in ["Graduate Engineer", "Software Engineer", "Senior Full Stack Developer (Angular)",
              "Technical Support Engineer", "Graduate Program 2027", "Controls Engineer", "Frontend Developer"]:
        print(t, "->", title_verdict(t))
