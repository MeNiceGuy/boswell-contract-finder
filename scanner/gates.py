"""Screening gates for Boswell Consulting Agency LLC.

Patterns mirror the in-app finder. Every gate here works on notice text only;
attached RFP documents still need a human or full-document read.
"""
import re

ORAL_ANY = re.compile(r"""\boral(s| presentations?| interviews?| discussions?| demonstrations?| briefings?)\b|\binterviews? (of|with) (the )?(offerors?|vendors?|proposers?|respondents?|key personnel|proposed staff|finalists)|\b(in-person|virtual|live) (presentation|interview|demonstration)s?\b|\bpresent(ation)? (to|before) the (evaluation|selection|technical|review) (panel|committee|board|team)|\b(may|will|shall|might) (also )?be (invited|asked|required|requested) to (an )?(interview|present|presentations?|demonstrat)""", re.I)
ORAL_GUARANTEE = re.compile(r"""\bno oral (presentations?|interviews?)\b|\boral presentations? (will|shall) not be (held|required|conducted|requested)|\bwill not (hold|conduct|require|request) oral|\b(evaluat\w+) (will be |is )?(based )?(solely|only|exclusively) on (the )?(basis of )?(the )?written|\bwritten[- ]only (evaluation|proposals?|submissions?)\b|\bnot be (required|asked|invited) to (give|make|provide|deliver|conduct) (an |any )?oral""", re.I)
LIVE_DUTY = re.compile(r"""\boral (briefings?|reports?|updates?)\b|\bpresent (the |its |final )?(findings|results|recommendations|report|plan|study)\b[^.]{0,60}\b(to|before) (the )?(board|council|commission|committee|city|county|agency|leadership|stakeholders|legislature)|\b(conduct|deliver|provide|facilitate|lead) (live |in-person |virtual |onsite |on-site )?(training sessions?|trainings?|workshops?|focus groups?|public meetings?|town halls?|listening sessions?|community meetings?)\b|\battend (all |regular |monthly |weekly |quarterly )?(meetings|board meetings|council meetings|public hearings)\b|\bpublic (hearings?|engagement meetings?)\b|\bkick-?off meetings?\b|\b(monthly|weekly|bi-?weekly|quarterly) (status |progress |coordination )?meetings\b|\b(telephone|teleconference|virtual|live) (panel|deliberation)s?\b|\blead(ing)? (the )?briefings?\b""", re.I)
REFS = re.compile(r"""\b(client|customer|business|professional|work) references\b|\breferences (from|of) (current |past |previous )?(clients|customers)\b|\b(three|3|two|2|five|5|four|4) (\(\d\) )?references\b|\bprovide (at least |a minimum of )?(\w+ )?references\b|\bpast performance questionnaires?\b|\bPPQs?\b|\breference (letters?|contacts?|forms?)\b""", re.I)
PAPER = re.compile(r"""\baudited financial|\bfinancial statements?\b|\bbalance sheets?\b|\bresumes?\b|\bstaff certifications?\b|\bCPARS\b|\bpast performance (records?|information|volume|history|citations?)\b|\b(two|three|2|3) years of (financial|tax|audited)|\bexamples? of (similar|comparable|relevant)\b[^.]{0,50}?\b(contracts|projects|work|engagements)\b""", re.I)
ONSITE_HARD = re.compile(r"""\bon-?site (work|presence|support|staff|staffing|personnel|services)\b|\bmust be located\b|\blocal presence\b|\bphysically present\b|\bwork (will be |shall be )?performed (on-?site|at the (government|agency|county|city|state)('s)? (site|facility|facilities|offices?))\b|\bin-person attendance (is )?required\b|\bwork\w* on-?site\b|\bperformed on-?site\b|\bon-?site at\b|\bat the government site\b|\bon (the )?premises\b""", re.I)
ONSITE_SOFT = re.compile(r"""\bmandatory (pre-?bid|pre-?proposal|pre-?submittal|site visit|conference|meeting)\b|\bon-?site\b|\bin[- ]person\b|\bface[- ]to[- ]face\b""", re.I)
CLEAR = re.compile(r"""\bsecurity clearance\b|\b(top )?secret clearance\b|\bTS\/SCI\b|\bclassified (information|access|work|material)\b|\bsuitability (determination|clearance|investigation|adjudication)s?\b|\b(FDA|agency) (security )?clearance\b""", re.I)
CRED = re.compile(r"""\blicensed (professional )?(engineers?|attorneys?|architects?|surveyors?|nurses?|appraisers?)\b|\bprofessional engineer(ing)? licen|\bcertified public account|\bCPA (firm|license)\b|\bregistered nurses?\b|\bbar (admission|membership)\b|\bPE licen|\bphysicians?\b|\bmedical doctors?\b|\bcertified (professional )?coders?\b|\bCPC\b|\bMD-110\b|\bexpert witness|\bboard[- ]certified\b""", re.I)
REMOTE = re.compile(r"""\bremote(ly)?\b|\btelework|\bvirtual(ly)?\b|\boff-?site\b|\bcontractor'?s?( own)? (facility|facilities|location)\b""", re.I)


def _oral_signal(t):
    """True when the text positively signals that orals may happen.

    Express no-orals guarantee spans are masked out first, so the word
    "oral" inside a guarantee ("will not hold oral presentations") is not
    itself a signal. Any orals language OUTSIDE a guarantee span is a
    signal, so a guarantee in one phase can never hide orals in another:
    the guarantee match does not short-circuit this check.
    """
    return bool(ORAL_ANY.search(ORAL_GUARANTEE.sub(" ", t)))


def eval_gates(text):
    """Return fails, flags, oral status and remote flag for a block of notice text."""
    t = text or ""
    fails, flags = [], []
    orals = None
    if _oral_signal(t):
        orals = "fail"
        fails.append("Oral presentation or interview possible")
    if LIVE_DUTY.search(t):
        orals = "fail"
        fails.append("Live meetings, briefings or training in scope")
    if orals != "fail":
        # Pass requires an express no-orals guarantee AND zero orals
        # signals (checked above). No guarantee at all means unconfirmed:
        # the item has not passed this gate and must not show as a match.
        orals = "guaranteed" if ORAL_GUARANTEE.search(t) else "unconfirmed"
    if REFS.search(t):
        fails.append("Client references or PPQs required")
    if PAPER.search(t):
        flags.append("Asks for financials, resumes or past performance")
    if ONSITE_HARD.search(t):
        fails.append("Staff required on site")
    elif ONSITE_SOFT.search(t):
        flags.append("Mentions in-person or on-site")
    if CLEAR.search(t):
        fails.append("Security clearance required")
    if CRED.search(t):
        fails.append("Requires a licensed credential")
    return {"fails": fails, "flags": flags, "orals": orals, "remote": bool(REMOTE.search(t))}
