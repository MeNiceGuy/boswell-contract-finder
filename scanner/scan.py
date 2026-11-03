"""Daily contract scan for Boswell Consulting Agency LLC.

Pulls open opportunities from SAM.gov and the Virginia, South Carolina,
North Carolina and Nevada portals, scores each against config/profile.json,
applies the screening gates, and writes docs/data/results.json for the
GitHub Pages viewer.

Run locally:  python scanner/scan.py
Optional env: SAM_API_KEY (used if SAM.gov blocks the public search endpoint)
"""
import base64
import datetime as dt
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

from gates import eval_gates

ROOT = Path(__file__).resolve().parent.parent
PROFILE = json.loads((ROOT / "config" / "profile.json").read_text())
OUT = ROOT / "docs" / "data" / "results.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

TYPE_LABEL = {"o": "Solicitation", "k": "Combined synopsis/solicitation", "r": "Sources sought",
              "p": "Presolicitation", "s": "Special notice", "a": "Award notice", "u": "Justification"}
TYPE_FROM_NAME = {"solicitation": "o", "combined synopsis/solicitation": "k", "sources sought": "r",
                  "presolicitation": "p", "special notice": "s", "award notice": "a", "justification": "u"}
SET_ASIDE_LABEL = {"SBA": "Total small business", "SBP": "Partial small business", "8A": "8(a)",
                   "8AN": "8(a) sole source", "WOSB": "WOSB", "EDWOSB": "EDWOSB", "SDVOSBC": "SDVOSB",
                   "SDVOSBS": "SDVOSB sole source", "VSA": "VOSB (VA)", "VSS": "VOSB sole source (VA)",
                   "HZC": "HUBZone", "HZS": "HUBZone sole source"}
GOOD_STATE_CATEGORY = re.compile(r"consult|professional", re.I)
NOW = dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------- helpers
def get(url, **kw):
    last = None
    for attempt in range(3):
        try:
            r = S.get(url, timeout=60, **kw)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(2 + attempt * 3)
    raise RuntimeError(last or "request failed")


def strip_html(h):
    t = re.sub(r"<(br|/p|/li|/div|/tr)[^>]*>", "\n", h or "", flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


def to_iso(s):
    """Parse the date formats the portals use into ISO 8601 (Eastern time assumed)."""
    if not s:
        return ""
    s = str(s).strip()
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=-5)))
        return d.isoformat()
    except ValueError:
        pass
    c = re.sub(r"\s+-\s+", " ", s)
    c = re.sub(r"(\d)\s*(am|pm)\b", lambda m: m.group(1) + " " + m.group(2).upper(), c, flags=re.I)
    for fmt in ("%B %d, %Y %I:%M %p", "%B %d, %Y", "%m/%d/%Y %I:%M %p", "%m/%d/%Y", "%m/%d/%Y %H:%M"):
        try:
            d = dt.datetime.strptime(c, fmt).replace(tzinfo=dt.timezone(dt.timedelta(hours=-5)))
            return d.isoformat()
        except ValueError:
            continue
    return ""


def days_left(iso):
    if not iso:
        return None
    try:
        return (dt.datetime.fromisoformat(iso) - NOW).days
    except ValueError:
        return None


# ---------------------------------------------------------------- SAM.gov
def sam_public(params):
    q = {"index": "opp", "page": "0", "mode": "search", "is_active": "true", "sort": "-modifiedDate"}
    q.update(params)
    url = "https://sam.gov/api/prod/sgs/v1/search/?" + "&".join(f"{k}={requests.utils.quote(str(v), safe=',')}" for k, v in q.items())
    r = get(url, headers={"Accept": "application/json"})
    return r.json().get("_embedded", {}).get("results", [])


def sam_norm(r, naics=None, set_aside=None):
    org = r.get("organizationHierarchy") or []
    by = lambda lvl: next((o.get("name", "") for o in org if o.get("level") == lvl), "")
    desc = strip_html(((r.get("descriptions") or [{}])[0]).get("content", ""))
    return {"id": r["_id"], "src": "SAM", "title": r.get("title") or "Untitled notice",
            "sol": r.get("solicitationNumber") or "", "type": (r.get("type") or {}).get("code", ""),
            "dept": by(1), "agency": by(2), "office": by(3), "posted": r.get("publishDate") or "",
            "due": r.get("responseDate") or r.get("responseDateActual") or "", "snippet": desc[:260],
            "desc": desc, "naics": [naics] if naics else [],
            "set_aside": set_aside or r.get("typeOfSetAside") or r.get("setAside") or "",
            "category": "", "url": f"https://sam.gov/opp/{r['_id']}/view"}


def scan_sam_public():
    found = {}
    types = ",".join(PROFILE["notice_types"])
    for n in PROFILE["naics"]:
        for r in sam_public({"naics": n["code"], "notice_type": types, "size": "100"}):
            if r.get("isCanceled"):
                continue
            it = found.get(r["_id"])
            if it:
                if n["code"] not in it["naics"]:
                    it["naics"].append(n["code"])
            else:
                found[r["_id"]] = sam_norm(r, naics=n["code"])
    for q in PROFILE["federal_searches"]:
        for r in sam_public({"q": f'"{q}"', "notice_type": types, "size": "50"}):
            if not r.get("isCanceled") and r["_id"] not in found:
                found[r["_id"]] = sam_norm(r)
    codes = ",".join(n["code"] for n in PROFILE["naics"])
    for sa in PROFILE["set_asides"]:
        for r in sam_public({"naics": codes, "set_aside": sa, "notice_type": types, "size": "100"}):
            if r["_id"] in found:
                found[r["_id"]]["set_aside"] = sa
    return list(found.values())


def sam_detail_public(it):
    r = get(f"https://sam.gov/api/prod/opps/v2/opportunities/{it['id']}", headers={"Accept": "application/json"}).json()
    d2 = r.get("data2") or {}
    body = strip_html(((r.get("description") or [{}])[0]).get("body", ""))
    sa = (d2.get("solicitation") or {}).get("setAside") or ""
    naics = [c for n in (d2.get("naics") or []) for c in (n.get("code") or [])]
    return body, sa, naics


def scan_sam_official(key):
    """Fallback: the official Opportunities API (needs a free SAM.gov API key)."""
    found = {}
    frm = (NOW - dt.timedelta(days=120)).strftime("%m/%d/%Y")
    to = NOW.strftime("%m/%d/%Y")
    allowed = set(PROFILE["notice_types"])
    def pull(params):
        q = {"api_key": key, "postedFrom": frm, "postedTo": to, "limit": "1000"}
        q.update(params)
        return get("https://api.sam.gov/opportunities/v2/search", params=q).json().get("opportunitiesData") or []
    def norm(o, naics=None):
        t = TYPE_FROM_NAME.get((o.get("type") or "").strip().lower(), "")
        path = (o.get("fullParentPathName") or "").split(".")
        return {"id": o.get("noticeId"), "src": "SAM", "title": o.get("title") or "Untitled notice",
                "sol": o.get("solicitationNumber") or "", "type": t, "dept": path[0] if path else "",
                "agency": path[1] if len(path) > 1 else "", "office": path[-1] if len(path) > 2 else "",
                "posted": o.get("postedDate") or "", "due": o.get("responseDeadLine") or "",
                "snippet": "", "desc": "", "naics": [naics or o.get("naicsCode") or ""],
                "set_aside": o.get("typeOfSetAside") or "", "category": "",
                "url": o.get("uiLink") or f"https://sam.gov/opp/{o.get('noticeId')}/view",
                "desc_url": o.get("description") or ""}
    for n in PROFILE["naics"]:
        for o in pull({"ncode": n["code"]}):
            if (o.get("active") or "").lower() != "yes":
                continue
            it = norm(o, n["code"])
            if it["type"] in allowed and it["id"] not in found:
                found[it["id"]] = it
    for q in PROFILE["federal_searches"]:
        for o in pull({"title": q}):
            it = norm(o)
            if (o.get("active") or "").lower() == "yes" and it["type"] in allowed and it["id"] not in found:
                found[it["id"]] = it
    return list(found.values())


def sam_detail_official(it, key):
    if not it.get("desc_url"):
        return "", it.get("set_aside", ""), it.get("naics", [])
    r = get(it["desc_url"], params={"api_key": key})
    try:
        body = strip_html(r.json().get("description", ""))
    except ValueError:
        body = strip_html(r.text)
    return body, it.get("set_aside", ""), it.get("naics", [])


# ---------------------------------------------------------------- states
def scan_va():
    url = ("https://mvendor.cgieva.com/Vendor/public/solrconnect.jsp?q=*:*&fq=status:Open&rows=1000&wt=json"
           "&fl=id,internalid,shortdesc,longdesc,agencyname,closedate,pubdate,category,doccddesc,setasideshortdesc,workloc")
    docs = get(url).json().get("response", {}).get("docs", [])
    out = []
    for d in docs:
        desc = strip_html(d.get("longdesc") or "")
        sa = d.get("setasideshortdesc") or ""
        if isinstance(sa, list):
            sa = sa[0] if sa else ""
        out.append({"id": f"VA-{d.get('id') or d.get('internalid')}", "src": "VA",
                    "title": (d.get("shortdesc") or "Untitled").strip(),
                    "sol": " ".join(x for x in [re.sub(r"\s*\(.*\)", "", d.get("doccddesc") or ""), str(d.get("internalid") or "")] if x),
                    "type": "", "dept": "Virginia", "agency": d.get("agencyname") or "", "office": d.get("workloc") or "",
                    "posted": d.get("pubdate") or "", "due": d.get("closedate") or "", "snippet": desc[:260], "desc": desc[:5000],
                    "category": d.get("category") or "", "va_small": sa, "naics": [], "set_aside": "",
                    "url": "https://mvendor.cgieva.com/Vendor/public/AllOpportunities.jsp"})
    return out


def scan_sc():
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).strftime("%Y-%m-%d")
    out = []
    for code, label in (("4", "Consultant/Professional"), ("11", "Services"), ("121", "Auditing")):
        page = f"https://scbo.sc.gov/online-edition?c={code}-{today}"
        raw = get(page).text
        for block in raw.split("<b>Ad Title:</b>")[1:]:
            def field(lab):
                m = re.search(r"<b>\s*" + re.escape(lab) + r":?\s*</b>(.*?)(?=<b>|$)", block, re.S)
                return m.group(1) if m else ""
            title = strip_html(block.split("<b>")[0])
            agency = strip_html(field("Purchasing Agent/Entity"))
            sol = strip_html(field("Solicitation #"))
            desc = strip_html(field("Description"))
            link_seg = field("Full Details / Download")
            link = re.search(r'href="(https?://[^"]+)"', link_seg) or re.search(r"(https?://\S+)", strip_html(link_seg))
            out.append({"id": f"SC-{(sol or title)[:80]}-{agency[:30]}", "src": "SC", "title": title, "sol": sol,
                        "type": "", "dept": "South Carolina", "agency": agency, "office": "",
                        "posted": to_iso(strip_html(field("Ad Publish Date"))),
                        "due": to_iso(strip_html(field("Bid/Submittal Due Date"))),
                        "snippet": desc[:260], "desc": desc[:5000], "category": label, "naics": [], "set_aside": "",
                        "url": html.unescape(link.group(1)) if link else page})
    return out


def scan_nc():
    page = S.get("https://evp.nc.gov/solicitations/", timeout=60)
    page.raise_for_status()
    t = page.text
    tok = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', t) or re.search(r'value="([^"]+)"[^>]*name="__RequestVerificationToken"', t)
    lay_attr = re.search(r'data-view-layouts="([^"]+)"', t)
    get_url = re.search(r'data-get-url="([^"]+)"', t)
    if not (tok and lay_attr and get_url):
        raise RuntimeError("eVP page layout changed; search grid not found")
    lay = json.loads(base64.b64decode(html.unescape(lay_attr.group(1))))[0]
    body = {"base64SecureConfiguration": lay["Base64SecureConfiguration"], "sortExpression": lay.get("SortExpression", ""),
            "search": "", "page": 1, "pageSize": 1000, "pagingCookie": "", "filter": None, "metaFilter": "3=0",
            "nlSearchFilter": "", "timezoneOffset": 300, "customParameters": [], "entityName": None, "entityId": None}
    r = S.post("https://evp.nc.gov" + html.unescape(get_url.group(1)), json=body, timeout=90,
               headers={"__RequestVerificationToken": html.unescape(tok.group(1)), "X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    out = []
    for rec in r.json().get("Records") or []:
        a = {x.get("Name"): (x.get("DisplayValue") if x.get("DisplayValue") is not None else x.get("Value")) for x in rec.get("Attributes", [])}
        if str(a.get("statuscode", "")).lower() != "open":
            continue
        desc = strip_html(str(a.get("evp_description") or ""))
        gid = a.get("evp_solicitationid") or rec.get("Id")
        out.append({"id": f"NC-{a.get('evp_solicitationnbr') or gid}", "src": "NC", "title": str(a.get("evp_name") or "Untitled"),
                    "sol": str(a.get("evp_solicitationnbr") or ""), "type": "", "dept": "North Carolina",
                    "agency": str(a.get("owningbusinessunit") or ""), "office": "", "posted": to_iso(a.get("evp_posteddate")),
                    "due": to_iso(a.get("evp_opendate")), "snippet": desc[:260], "desc": desc[:5000], "category": "",
                    "naics": [], "set_aside": "",
                    "url": f"https://evp.nc.gov/solicitations/details/?id={gid}" if gid else "https://evp.nc.gov/solicitations/"})
    return out


def scan_nv():
    raw = get("https://nevadaepro.com/bso/view/search/external/advancedSearchBid.xhtml?openBids=true").text
    out = []
    for row in re.findall(r"<tr[^>]*data-ri=[^>]*>(.*?)</tr>", raw, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if len(cells) < 10:
            continue
        href = re.search(r'href="([^"]+)"', cells[0])
        doc = strip_html(cells[0])
        org, desc, opening, status, alt = (strip_html(cells[i]) for i in (2, 6, 7, 9, 10 if len(cells) > 10 else 9))
        out.append({"id": f"NV-{doc}", "src": "NV", "title": desc or doc, "sol": doc, "type": "", "dept": "Nevada",
                    "agency": org, "office": alt, "posted": "", "due": to_iso(opening), "snippet": alt,
                    "desc": ". ".join(x for x in (desc, alt) if x), "category": "", "naics": [], "set_aside": "",
                    "url": "https://nevadaepro.com" + html.unescape(href.group(1)) if href else
                    "https://nevadaepro.com/bso/view/search/external/advancedSearchBid.xhtml?openBids=true"})
    return out


# ---------------------------------------------------------------- scoring
def score(it):
    p = PROFILE
    why = []
    s = 0
    title, snip, body = (it.get("title") or "").lower(), (it.get("snippet") or "").lower(), (it.get("desc") or "").lower()
    tiers = [next((n["tier"] for n in p["naics"] if n["code"] == c), None) for c in it.get("naics") or []]
    if "core" in tiers:
        s += 35; why.append("Core NAICS " + ", ".join(it["naics"]))
    elif "secondary" in tiers:
        s += 22; why.append("Secondary NAICS " + ", ".join(it["naics"]))
    kw, hits = 0, []
    for k in p["keywords"]:
        if k in title:
            kw += 7; hits.append(k)
        elif k in snip or k in body:
            kw += 4; hits.append(k)
    is_state = it["src"] != "SAM"
    kw = min(kw, 45 if is_state else 30)
    s += kw
    if hits:
        why.append("Keywords: " + ", ".join(hits[:4]))
    relevant = bool(tiers and any(tiers)) or bool(hits)
    if is_state:
        s += 12
        if it.get("category") and GOOD_STATE_CATEGORY.search(it["category"]):
            s += 15; why.append("Category: " + it["category"]); relevant = True
    ex = [k for k in p["exclude"] if k in title]
    exs = [k for k in p["exclude"] if k not in title and k in snip]
    if ex:
        s -= 20; why.append("Outside your services: " + ex[0])
    elif exs:
        s -= 8; why.append("Summary mentions " + exs[0])
    if not is_state:
        s += {"o": 15, "k": 15, "r": 12, "p": 8}.get(it.get("type"), 0)
    g = it.get("gate") or eval_gates(" ".join([it.get("title", ""), it.get("snippet", ""), it.get("desc", "")]))
    fails, flags = list(g["fails"]), list(g["flags"])
    # Eligibility fails closed: only an affirmatively eligible set-aside
    # confirms eligibility. A portal value of NONE / N/A, or no value at
    # all, is unknown, never eligible.
    sa = (it.get("set_aside") or "").strip()
    if sa.upper() in ("NONE", "N/A", "NA"):
        sa = ""
    elig = "unconfirmed"
    if sa:
        lab = SET_ASIDE_LABEL.get(sa, sa)
        if sa in p["set_asides"]:
            s += 15; why.append(lab + " set-aside you qualify for"); elig = "confirmed"
        else:
            fails.append(lab + " set-aside you don't qualify for"); elig = "failed"
    if it["src"] == "VA" and it.get("va_small"):
        if p.get("swam"):
            s += 10; why.append("Virginia " + it["va_small"]); elig = "confirmed"
        else:
            fails.append("Virginia " + it["va_small"] + " needs SWaM certification"); elig = "failed"
    d = days_left(it.get("due"))
    if d is not None and d < p["min_days"]:
        fails.append("Deadline too tight")
    hay = (it.get("title", "") + " " + it.get("sol", "")).lower()
    if any(h and h.lower() in hay for h in p.get("handled", [])):
        fails.append("Already handled")
    if g["orals"] == "guaranteed":
        s += 10; why.append("Notice states no oral presentations")
    if g["remote"]:
        s += 5; why.append("Mentions remote or virtual work")
    s -= 8 * len(flags)
    out = bool(fails)
    # Unconfirmed bucket: not screened out, but not a pass either. An item
    # lands here when the notice text carries no express no-orals
    # guarantee, or when its set-aside eligibility could not be
    # confirmed. Unconfirmed items never display as matches or fits.
    unconf = []
    if not out:
        if g["orals"] == "unconfirmed":
            unconf.append("Orals not confirmed")
        if elig == "unconfirmed":
            unconf.append("Eligibility not confirmed")
    it["unconfirmed"] = bool(unconf)
    it["view"] = {"fails": fails, "flags": flags, "orals": g["orals"], "remote": g["remote"],
                  "unconfirmed": unconf, "eligibility": elig}
    it["out"] = out
    it["score"] = max(0, min(15 if out else 100, round(s)))
    it["why"] = why
    it["relevant"] = relevant
    return it


# ---------------------------------------------------------------- main
def main():
    results, counts, failures = [], {}, []
    key = os.environ.get("SAM_API_KEY", "").strip()
    sam_mode = None
    runners = {"VA": scan_va, "SC": scan_sc, "NC": scan_nc, "NV": scan_nv}
    if "SAM" in PROFILE["sources"]:
        try:
            items = scan_sam_public(); sam_mode = "public"
        except Exception as e:
            if key:
                try:
                    items = scan_sam_official(key); sam_mode = "official"
                except Exception as e2:
                    items = []; failures.append({"source": "SAM", "message": f"SAM.gov API failed: {e2}"})
            else:
                items = []
                failures.append({"source": "SAM", "message": f"SAM.gov blocked the public search ({e}). Add a free SAM.gov API key as the SAM_API_KEY repository secret."})
        counts["SAM"] = len(items); results += items
        print(f"SAM ({sam_mode}): {len(items)}", file=sys.stderr)
    for code in ("VA", "SC", "NC", "NV"):
        if code not in PROFILE["sources"]:
            continue
        try:
            items = runners[code]()
            counts[code] = len(items); results += items
            print(f"{code}: {len(items)}", file=sys.stderr)
            if not items:
                failures.append({"source": code, "message": "No open notices came back; the portal may have changed."})
        except Exception as e:
            counts[code] = 0
            failures.append({"source": code, "message": str(e)[:300]})
            print(f"{code} failed: {e}", file=sys.stderr)

    results = [it for it in results if (days_left(it.get("due")) is None or days_left(it.get("due")) >= 0)]
    for it in results:
        score(it)

    # Read the full notice text for every surviving federal candidate and
    # re-screen. The detail read is also what supplies each candidate's
    # real set-aside value, so it can no longer stop at the top 20: a
    # candidate whose set-aside stays unknown after this read is marked
    # unconfirmed on eligibility instead of counting as eligible.
    top = sorted((i for i in results if i["src"] == "SAM" and not i["out"]), key=lambda i: -i["score"])
    for it in top:
        try:
            body, sa, naics = sam_detail_public(it) if sam_mode == "public" else sam_detail_official(it, key)
            if sa and not it.get("set_aside"):
                it["set_aside"] = sa
            if naics:
                it["naics"] = sorted(set(it.get("naics", []) + [n for n in naics if n]))
            if body:
                it["desc"] = body[:8000]
                it["gate"] = eval_gates(it["title"] + " " + body)
                it["screened"] = "full notice"
            score(it)
            time.sleep(0.5)
        except Exception as e:
            print(f"detail failed for {it['id']}: {e}", file=sys.stderr)

    keep = [i for i in results if i["relevant"] or i["score"] >= 25]
    for i in keep:
        i.pop("gate", None); i.pop("desc_url", None)
        i["desc"] = (i.get("desc") or "")[:1500]
    keep.sort(key=lambda i: (i["out"], i.get("unconfirmed", False), -i["score"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": NOW.isoformat(), "company": PROFILE["company"], "counts": counts,
        "sam_mode": sam_mode, "failures": failures, "min_days": PROFILE["min_days"],
        "set_asides": PROFILE["set_asides"], "manual_portals": PROFILE["manual_portals"],
        "items": keep}, indent=1))
    live = [i for i in keep if not i["out"] and not i.get("unconfirmed")]
    unc = [i for i in keep if i.get("unconfirmed") and not i["out"]]
    print(f"Wrote {len(keep)} notices ({len(live)} confirmed matches, {len(unc)} unconfirmed, "
          f"{sum(1 for i in live if i['score'] >= 65)} strong).", file=sys.stderr)


if __name__ == "__main__":
    main()
