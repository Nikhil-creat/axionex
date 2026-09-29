"""Trust & Compliance Auditor — fetches a storefront URL and runs real checks across legal pages,
consent, data-minimisation, tracking disclosure, accessibility (WCAG contrast/labels), review and
claim integrity, business-identity disclosure, and India's DPDP Act 2023 readiness.

This is best-effort static analysis of the HTML/response actually returned, not a legal opinion —
every report line carries the disclaimer required in `DISCLAIMER`. Nothing here verifies truth
claims, review authenticity, or image licensing; it flags patterns a human should check.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

DISCLAIMER = "Not legal advice — have a lawyer review before you rely on this."
Status = str  # "pass" | "warn" | "fail" | "info" | "unknown"

TRACKERS = {
    "google-analytics.com": "Google Analytics", "googletagmanager.com": "Google Tag Manager",
    "connect.facebook.net": "Meta Pixel", "hotjar.com": "Hotjar", "mixpanel.com": "Mixpanel",
    "segment.com": "Segment", "doubleclick.net": "DoubleClick", "clarity.ms": "Microsoft Clarity",
    "cdn.amplitude.com": "Amplitude", "snap.licdn.com": "LinkedIn Insight",
}
CONSENT_MARKERS = ("cookiebot", "onetrust", "cookieyes", "termly", "iubenda", "cookie-consent",
                  "cookie_consent", "cookieconsent", "gdpr-consent", "accept cookies", "manage cookies")
CLAIM_PATTERNS = [
    r"\b100%\s*(guarantee|guaranteed|risk[- ]?free|safe)\b", r"\bclinically proven\b", r"\bno side effects\b",
    r"\bcures?\b", r"\binstant results?\b", r"\b#\s?1\s+(in|worldwide|india)\b", r"\bbest in the world\b",
    r"\bmiracle\b", r"\bguaranteed (results|returns|income)\b", r"\bdoctor recommended\b(?!.{0,40}(study|source|trial))",
]
VAGUE_LABELS = {"click here", "here", "read more", "submit", "learn more", "link", "go", "more"}
GST_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b")
CIN_RE = re.compile(r"\b[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}\b")
PHONE_RE = re.compile(r"(?:\+91[\s-]?|0)?[6-9]\d{9}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PIN_RE = re.compile(r"\b\d{6}\b")
SECRET_RE = re.compile(r"\b(AKIA[0-9A-Z]{16}|sk_live_[0-9a-zA-Z]{16,}|AIza[0-9A-Za-z_-]{20,})\b")
HEX_RE = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


@dataclass
class CheckResult:
    key: str
    label: str
    status: Status
    detail: str
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "status": self.status, "detail": self.detail, "evidence": self.evidence[:8]}


CHECKLIST = [
    ("privacy_policy", "Privacy policy page"), ("terms_page", "T&C's page"), ("cookies_policy", "Cookies policy"),
    ("cookie_consent", "Check for cookie consent"), ("refund_policy", "Refund policy"), ("form_consent", "Form consent"),
    ("data_minimisation", "Only collect necessary data"), ("tracking", "Check tracking"),
    ("third_party_embeds", "Check 3rd party embeds"), ("accessibility", "Fix accessibility"),
    ("alt_text", "Alt text on images"), ("colour_contrast", "Check colour contrast"),
    ("keyboard_forms", "Keyboard-friendly forms"), ("button_labels", "Clear button labels"),
    ("fake_reviews", "Remove fake reviews"), ("false_claims", "Remove false claims"),
    ("business_details", "Business details"), ("image_copyright", "Image copyright"),
    ("dpdp_compliant", "DPDP Act compliant"), ("other_risks", "Flag other risks"),
]


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    lr, lg, lb = lin(r), lin(g), lin(b)
    return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    l1, l2 = sorted((_luminance(hex_a), _luminance(hex_b)), reverse=True)
    return round((l1 + 0.05) / (l2 + 0.05), 2)


def _find_link(soup: BeautifulSoup, *needles: str) -> list[str]:
    hits = []
    for a in soup.find_all("a", href=True):
        blob = f"{a.get('href', '')} {a.get_text(' ', strip=True)}".lower()
        if any(n in blob for n in needles):
            hits.append(a.get("href"))
    return hits


class ComplianceScanner:
    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    async def scan(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.timeout,
                                     headers={"User-Agent": "AxioNexComplianceBot/1.0 (+trust-audit)"}) as client:
            resp = await client.get(parsed.geturl())
        html = resp.text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        checks: dict[str, CheckResult] = {}

        def add(key: str, label: str, status: Status, detail: str, evidence: list[str] | None = None) -> None:
            checks[key] = CheckResult(key, label, status, detail, evidence or [])

        # 1-5: legal pages -------------------------------------------------
        priv = _find_link(soup, "privacy")
        add("privacy_policy", "Privacy policy page", "pass" if priv else "fail",
            f"Found {len(priv)} link(s)." if priv else "No link with 'privacy' in href or text was found.", priv)
        terms = _find_link(soup, "terms", "t&c", "conditions of use", "conditions of sale")
        add("terms_page", "T&C's page", "pass" if terms else "fail",
            f"Found {len(terms)} link(s)." if terms else "No terms-and-conditions link was found.", terms)
        cookies_link = _find_link(soup, "cookie")
        add("cookies_policy", "Cookies policy", "pass" if cookies_link else "fail",
            f"Found {len(cookies_link)} link(s)." if cookies_link else "No cookies-policy link was found.", cookies_link)
        low_html = html.lower()
        consent_hits = [m for m in CONSENT_MARKERS if m in low_html]
        add("cookie_consent", "Check for cookie consent", "pass" if consent_hits else "warn",
            f"Detected consent tooling/markup: {', '.join(consent_hits)}." if consent_hits
            else "No known consent-management markup or banner text was detected — verify manually.", consent_hits)
        refund = _find_link(soup, "refund", "return polic", "cancellation")
        add("refund_policy", "Refund policy", "pass" if refund else "warn",
            f"Found {len(refund)} link(s)." if refund else "No refund/return policy link was found.", refund)

        # 6-7: forms / data minimisation ------------------------------------
        forms = soup.find_all("form")
        consent_boxes = 0
        for f in forms:
            for cb in f.find_all("input", {"type": "checkbox"}):
                near = (cb.parent.get_text(" ", strip=True) if cb.parent else "").lower()
                if any(w in near for w in ("agree", "consent", "terms", "privacy")):
                    consent_boxes += 1
        add("form_consent", "Form consent", "pass" if consent_boxes else ("info" if not forms else "warn"),
            f"{consent_boxes} consent checkbox(es) found across {len(forms)} form(s)." if forms else "No forms on this page.")
        sensitive_inputs = [i.get("name") or i.get("id") or i.get("type") for f in forms
                            for i in f.find_all("input")
                            if any(k in (i.get("name", "") + i.get("id", "")).lower()
                                   for k in ("ssn", "aadhar", "aadhaar", "passport", "pan_no", "dob"))]
        add("data_minimisation", "Only collect necessary data", "warn" if sensitive_inputs else "pass",
            f"Sensitive-looking fields requested: {', '.join(x for x in sensitive_inputs if x)}." if sensitive_inputs
            else "No obviously excessive/sensitive form fields detected (heuristic only).", sensitive_inputs)

        # 8-9: tracking / embeds --------------------------------------------
        scripts = [s.get("src", "") for s in soup.find_all("script", src=True)]
        found_trackers = sorted({name for src in scripts for dom, name in TRACKERS.items() if dom in src})
        add("tracking", "Check tracking", "info" if found_trackers else "pass",
            f"Trackers detected: {', '.join(found_trackers)}. Disclose these in the privacy/cookie policy." if found_trackers
            else "No common third-party trackers detected.", found_trackers)
        iframes = [i.get("src", "") for i in soup.find_all("iframe", src=True)]
        ext_embeds = sorted({urlparse(s).netloc for s in iframes if urlparse(s).netloc and parsed.netloc not in s})
        add("third_party_embeds", "Check 3rd party embeds", "info" if ext_embeds else "pass",
            f"External embeds from: {', '.join(ext_embeds)}." if ext_embeds else "No external iframes detected.", ext_embeds)

        # 10-14: accessibility ------------------------------------------------
        html_tag = soup.find("html")
        acc_issues = []
        if not (html_tag and html_tag.get("lang")):
            acc_issues.append("<html> is missing a lang attribute")
        headings = [int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))]
        if headings and headings[0] != 1:
            acc_issues.append("page does not start with an <h1>")
        if any(b - a > 1 for a, b in zip(headings, headings[1:])):
            acc_issues.append("heading levels skip (e.g. h2 straight to h4)")
        add("accessibility", "Fix accessibility", "pass" if not acc_issues else "warn",
            "; ".join(acc_issues) if acc_issues else "No structural accessibility issues detected (heuristic scan).", acc_issues)

        imgs = soup.find_all("img")
        missing_alt = [i.get("src", "?") for i in imgs if not (i.get("alt") or "").strip()]
        add("alt_text", "Alt text on images", "pass" if not missing_alt else "fail",
            f"{len(missing_alt)} of {len(imgs)} images are missing alt text." if imgs else "No images found.", missing_alt)

        pairs: list[tuple[str, str, str]] = []
        for tag in soup.find_all(style=True):
            style = tag.get("style", "")
            c = re.search(r"(?<!background-)color\s*:\s*(" + HEX_RE.pattern + ")", style, re.I)
            b = re.search(r"background(?:-color)?\s*:\s*(" + HEX_RE.pattern + ")", style, re.I)
            if c and b:
                pairs.append((c.group(1), b.group(1), tag.get_text(" ", strip=True)[:40]))
        low_contrast = [(a, b, snip, contrast_ratio(a, b)) for a, b, snip in pairs if contrast_ratio(a, b) < 4.5]
        add("colour_contrast", "Check colour contrast",
            "unknown" if not pairs else ("pass" if not low_contrast else "fail"),
            (f"Checked {len(pairs)} inline colour/background pair(s); {len(low_contrast)} fall below the WCAG AA "
             f"4.5:1 ratio for normal text.") if pairs else "No inline colour+background pairs found to check; run a full-page contrast tool for CSS-file styling.",
            [f"{a} on {b} = {r}:1 ({snip})" for a, b, snip, r in low_contrast])

        kb_issues = []
        for el in soup.find_all(True, onclick=True):
            if el.name in ("div", "span") and not el.get("role") and el.get("tabindex") is None:
                kb_issues.append(f"<{el.name}> uses onclick without role/tabindex")
        for f in forms:
            for i in f.find_all(("input", "select", "textarea")):
                has_label = bool(i.get("aria-label") or i.get("aria-labelledby")
                                or (i.get("id") and soup.find("label", {"for": i.get("id")})))
                if not has_label and i.get("type") not in ("hidden", "submit", "button"):
                    kb_issues.append(f"unlabelled <{i.name}> field ({i.get('name') or i.get('type')})")
        add("keyboard_forms", "Keyboard-friendly forms", "pass" if not kb_issues else "warn",
            f"{len(kb_issues)} issue(s) found." if kb_issues else "No keyboard/label issues detected (heuristic scan).", kb_issues[:10])

        vague = []
        for el in soup.find_all(("a", "button")):
            label = el.get_text(" ", strip=True).lower()
            if label in VAGUE_LABELS or (not label and not el.get("aria-label") and not el.get("title")):
                vague.append(el.get_text(" ", strip=True) or f"<{el.name}> (icon-only, no aria-label)")
        add("button_labels", "Clear button labels", "pass" if not vague else "warn",
            f"{len(vague)} vague or unlabelled button/link(s), e.g. {', '.join(vague[:3]) or '—'}." if vague
            else "Button and link labels look descriptive.", vague)

        # 15-16: reviews / claims ---------------------------------------------
        review_texts, ratings = [], []
        for tag in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(tag.string or "{}")
            except Exception:
                continue
            for node in (data if isinstance(data, list) else [data]):
                if not isinstance(node, dict):
                    continue
                if node.get("@type") == "Review":
                    review_texts.append((node.get("reviewBody") or "").strip())
                    rv = node.get("reviewRating", {})
                    if isinstance(rv, dict) and rv.get("ratingValue"):
                        ratings.append(str(rv["ratingValue"]))
        dup_reviews = len(review_texts) - len({t for t in review_texts if t})
        all_top_rating = bool(ratings) and len(set(ratings)) == 1 and ratings[0] in ("5", "5.0")
        review_flags = ([f"{dup_reviews} duplicate review text(s)"] if dup_reviews > 0 else []) + \
                      (["every parsed rating is a perfect score — verify these are genuine"] if all_top_rating else [])
        add("fake_reviews", "Remove fake reviews", "warn" if review_flags else ("info" if review_texts else "unknown"),
            "; ".join(review_flags) if review_flags else
            (f"{len(review_texts)} structured review(s) parsed, nothing suspicious detected." if review_texts
             else "No schema.org Review markup found to check; reviews may be on another page."), review_flags)

        claim_hits = []
        for pat in CLAIM_PATTERNS:
            for m in re.finditer(pat, text, re.I):
                claim_hits.append(text[max(0, m.start() - 25):m.end() + 25].strip())
        add("false_claims", "Remove false claims", "warn" if claim_hits else "pass",
            f"{len(claim_hits)} risky absolute/superlative phrase(s) found — verify each is substantiated." if claim_hits
            else "No high-risk absolute claim phrases detected (heuristic word-list scan).", claim_hits[:8])

        # 17-18: identity / imagery --------------------------------------------
        gst = GST_RE.search(html) or GST_RE.search(text)
        cin = CIN_RE.search(html) or CIN_RE.search(text)
        phone = PHONE_RE.search(text)
        email = EMAIL_RE.search(text)
        pin = PIN_RE.search(text)
        present = {"GSTIN": bool(gst), "CIN": bool(cin), "phone": bool(phone), "email": bool(email), "postal code": bool(pin)}
        missing = [k for k, v in present.items() if not v]
        add("business_details", "Business details", "pass" if len(missing) <= 2 else "warn",
            f"Detected: {', '.join(k for k, v in present.items() if v) or 'nothing'}. "
            f"Not found: {', '.join(missing) or 'nothing'}.", missing)

        undecorated_imgs = [i.get("src") for i in imgs if not (i.get("alt", "") + i.get("title", "")).lower()
                            .__contains__("credit") and not i.get("data-license")]
        add("image_copyright", "Image copyright",
            "unknown",
            "Ownership can't be verified automatically. "
            f"{len(undecorated_imgs)} of {len(imgs)} image(s) carry no visible credit/licence attribute — "
            "run a reverse-image search on hero/product photos before publishing.", undecorated_imgs[:5])

        # 19: DPDP Act 2023 composite ------------------------------------------
        grievance = bool(re.search(r"grievance officer|data protection officer|nodal officer", text, re.I))
        retention = bool(re.search(r"data retention|delete your data|right to erasure|withdraw consent", text, re.I))
        cross_border = bool(re.search(r"cross[- ]border|outside india|data localis", text, re.I))
        dpdp_points = {"Privacy policy published": bool(priv), "Consent mechanism present": bool(consent_hits or consent_boxes),
                       "Data minimisation (no excess sensitive fields)": not sensitive_inputs,
                       "Grievance/DPO officer named": grievance, "Retention/erasure rights mentioned": retention,
                       "Cross-border transfer disclosed": cross_border}
        dpdp_score = round(100 * sum(dpdp_points.values()) / len(dpdp_points))
        add("dpdp_compliant", "DPDP Act compliant", "pass" if dpdp_score >= 80 else ("warn" if dpdp_score >= 50 else "fail"),
            f"DPDP readiness score {dpdp_score}/100. Missing: {', '.join(k for k, v in dpdp_points.items() if not v) or 'nothing obvious'}.",
            [k for k, v in dpdp_points.items() if not v])

        # 20: other risks ---------------------------------------------------
        risks = []
        if parsed.scheme != "https":
            risks.append("Site was not served over HTTPS")
        if parsed.scheme == "https" and re.search(r'src=["\']http://', html):
            risks.append("Mixed content: http:// resources embedded on an https page")
        for f in forms:
            if (f.get("action") or "").startswith("http://"):
                risks.append("A form submits over plain HTTP")
        if SECRET_RE.search(html):
            risks.append("A pattern resembling an exposed API key/secret was found in page source")
        sec_headers = {"content-security-policy", "x-frame-options", "strict-transport-security"}
        missing_headers = [h for h in sec_headers if h not in {k.lower() for k in resp.headers}]
        if missing_headers:
            risks.append(f"Missing security headers: {', '.join(missing_headers)}")
        add("other_risks", "Flag other risks", "pass" if not risks else "warn",
            "; ".join(risks) if risks else "No additional structural risks detected.", risks)

        ordered = [checks[k].to_dict() for k, _ in CHECKLIST]
        counts = {"pass": 0, "warn": 0, "fail": 0, "info": 0, "unknown": 0}
        for c in ordered:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
        score = round(100 * (counts["pass"] + 0.5 * counts["info"]) / len(ordered))
        return {"url": parsed.geturl(), "status_code": resp.status_code, "score": score, "counts": counts,
                "checks": ordered, "dpdp_score": dpdp_score, "disclaimer": DISCLAIMER}
