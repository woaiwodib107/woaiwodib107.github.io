#!/usr/bin/env python3
"""
Fetch publication data for Dongming Han from multiple academic sources.
Outputs data/publications.json for the academic homepage.

Pipeline order (see main()):
  1. DBLP — primary publication list
  2. Cache restore — pdf_url / video_url / citations from prior runs
  3. DOI publisher-page crawl — citation_pdf_url meta tag
  4. OpenAlex — open-access PDFs + citation counts (free, no key)
  5. Google Scholar — h-index / i10 (best-effort; often blocked)
  6. Manual override merge from data/publications_manual.json
  7. Local asset auto-link from assets/{pdf,video,teaser,...}/

Usage:
    python3 fetch_scholar.py                # Full fetch
    python3 fetch_scholar.py --use-cache    # Reuse cached publications, only re-merge manual + assets
    python3 fetch_scholar.py --no-scholar   # Skip Google Scholar
    python3 fetch_scholar.py --no-openalex  # Skip OpenAlex AND DOI publisher-page crawl
"""

import json
import os
import sys
import time
import random
import re
import argparse
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# --- Configuration ---
SCHOLAR_ID = "Mkmw3tQAAAAJ"
DBLP_PID = "231/6878"
AUTHOR_NAME = "Dongming Han"
AUTHOR_ALIASES = ["Dongming Han", "D. Han", "韩东明"]
CONTACT_EMAIL = "dongminghan@zju.edu.cn"
DEFAULT_AFFILIATION = "Hithink RoyalFlush AI Research Institute · Zhejiang University"
DEFAULT_INTERESTS = [
    "Code Generation & AIGC",
    "Information Visualization",
    "Visual Analytics",
    "Graph Visualization",
]

# DBLP merges all "Dongming Han" researchers. We disambiguate by checking for
# known collaborators. A paper is "confirmed" if it has any of these co-authors;
# other papers are kept but flagged with confidence="low" — the user can keep
# or exclude them via data/publications_manual.json. Grouped by source so the
# next person to add a name knows where it fits.
_VAG_LAB = {
    "wei chen", "minfeng zhu", "jiacheng pan", "haiyang zhu", "fangzhou guo",
    "rusheng pan", "yijing liu", "jiehui zhou", "xumeng wang", "yingcai wu",
    "luoxuan weng", "jianwei zhang", "xiaodong zhao", "yating wei",
    "zihan zhou", "tianye zhang", "ran chen", "zhen wen", "jian chen",
    "mingliang xu", "siwei tan", "jingrui he", "jiazhi xia", "nan cao",
}
_HITHINK = {
    "yujie ding", "tianyi ma", "bingcheng mao", "shuai jia",
}
KNOWN_COAUTHORS = _VAG_LAB | _HITHINK

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = DATA_DIR / "publications.json"
MANUAL_FILE = DATA_DIR / "publications_manual.json"

# Local asset folders that get auto-linked to publications by filename match.
ASSETS_DIR = Path(__file__).parent / "assets"

# URL-style assets: store relative file path on the publication
ASSET_FOLDERS_URL = {
    "pdf_url":      ("pdf",      [".pdf"]),
    "video_url":    ("video",    [".mp4", ".webm", ".mov"]),
    "appendix_url": ("appendix", [".pdf", ".zip"]),
    "slides_url":   ("slides",   [".pdf", ".pptx", ".key"]),
    "teaser_url":   ("teaser",   [".png", ".jpg", ".jpeg", ".webp", ".gif"]),
}
# Content-style assets: read the file's TEXT into the publication field
ASSET_FOLDERS_TEXT = {
    "tldr":     ("tldr",     [".txt", ".md"]),
    "abstract": ("abstract", [".txt", ".md"]),
}

# Expand DBLP venue abbreviations to readable names
VENUE_EXPANSIONS = {
    "IEEE Trans. Vis. Comput. Graph.": "IEEE Transactions on Visualization and Computer Graphics",
    "J. Comput. Sci. Technol.": "Journal of Computer Science and Technology",
    "Frontiers Comput. Sci.": "Frontiers of Computer Science",
    "Frontiers Inf. Technol. Electron. Eng.": "Frontiers of Information Technology & Electronic Engineering",
    "Vis. Informatics": "Visual Informatics",
    "Inf. Vis.": "Information Visualization",
    "IEEE VIS": "IEEE VIS",
    "VIS": "IEEE VIS",
    "CHI": "ACM CHI",
    "KDD": "ACM KDD",
}

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
]


# --- HTTP helper (no requests dep) ---
def http_get(url, timeout=30, headers=None):
    h = {"User-Agent": random.choice(USER_AGENTS),
         "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
         "Accept-Language": "en-US,en;q=0.9"}
    if headers:
        h.update(headers)
    req = Request(url, headers=h)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace"), resp.status


# ---------- DBLP fetcher ----------
def _is_preprint(pub):
    """True for arXiv/CoRR records. DBLP types these as 'article', so type alone
    can't distinguish a preprint from a real journal paper."""
    venue = (pub.get("venue") or "").strip().lower()
    doi = (pub.get("doi") or "").lower()
    return venue in ("corr", "arxiv") or venue.startswith("corr ") or "arxiv" in doi


def fetch_from_dblp():
    """Fetch publications from DBLP — reliable academic publication index."""
    url = f"https://dblp.org/pid/{DBLP_PID}.xml"
    print(f"[dblp] Fetching {url}")

    body, status = http_get(url)
    if status != 200:
        raise RuntimeError(f"DBLP returned {status}")

    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        # DBLP occasionally returns an HTML maintenance page with status 200.
        sample = body[:200].replace("\n", " ")
        raise RuntimeError(f"DBLP XML parse failed ({e}); body starts: {sample!r}") from e

    publications = []
    for r in root.findall("r"):
        for entry in r:  # 'article', 'inproceedings', 'incollection', etc.
            pub = {
                "title": "",
                "authors": "",
                "year": "",
                "venue": "",
                "type": entry.tag,
                "key": entry.attrib.get("key", ""),
                "citations": 0,
                "scholar_url": "",
                "pub_url": "",
                "pdf_url": "",
                "doi": "",
                "video_url": "",
                "project_url": "",
                "code_url": "",
            }

            authors = []
            ee_links = []

            for child in entry:
                tag = child.tag
                text = (child.text or "").strip()

                if tag == "author":
                    # Strip trailing ' 0001' disambiguators
                    name = re.sub(r"\s+\d{4}$", "", text)
                    authors.append(name)
                elif tag == "title":
                    pub["title"] = text.rstrip(".")
                elif tag == "year":
                    pub["year"] = text
                elif tag in ("journal", "booktitle"):
                    pub["venue"] = VENUE_EXPANSIONS.get(text, text)
                elif tag == "ee":
                    ee_links.append(text)
                elif tag == "url":
                    if not pub["pub_url"]:
                        pub["pub_url"] = text if text.startswith("http") else f"https://dblp.org/{text}"

            pub["authors"] = ", ".join(authors)

            # Detect author position: first / middle / last (corresponding)
            self_pos = None
            self_aliases_lower = {a.lower() for a in AUTHOR_ALIASES}
            for idx, a in enumerate(authors):
                if a.lower() in self_aliases_lower:
                    self_pos = idx
                    break
            if self_pos is not None and authors:
                if self_pos == 0:
                    pub["author_position"] = "first"
                elif self_pos == len(authors) - 1 and len(authors) >= 3:
                    pub["author_position"] = "last"
                else:
                    pub["author_position"] = "middle"

            # Confidence: do any known collaborators appear?
            author_set = {a.lower() for a in authors}
            pub["confidence"] = "high" if (author_set & KNOWN_COAUTHORS) else "low"

            # Pull DOI / publisher URL from <ee>
            for link in ee_links:
                if "doi.org" in link and not pub["doi"]:
                    pub["doi"] = link
                    if not pub["pub_url"]:
                        pub["pub_url"] = link
                elif not pub["pub_url"]:
                    pub["pub_url"] = link

            if pub["title"]:
                publications.append(pub)

    # Dedup by normalized title; drop errata; keep latest year (preprint→pub)
    by_title = {}
    for p in publications:
        if p["title"].lower().startswith("erratum"):
            continue
        # Normalize: lowercase, strip non-alnum, collapse whitespace
        norm = re.sub(r"[^\w\s]", "", p["title"].lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        if norm not in by_title:
            by_title[norm] = p
        else:
            # Prefer the real published venue over the preprint, then prefer the newer year.
            # NOTE: CoRR/arXiv entries are type="article" in DBLP, so a naive
            # "prefer article" rule would keep the preprint and discard the
            # conference version (e.g. SGCR: ASE 2025 vs CoRR 2025).
            old = by_title[norm]
            old_pre = _is_preprint(old)
            new_pre = _is_preprint(p)
            if old_pre != new_pre:
                # Exactly one is a preprint — always keep the published one.
                if old_pre:
                    by_title[norm] = p
            else:
                old_year = int(old.get("year") or 0)
                new_year = int(p.get("year") or 0)
                if new_year > old_year:
                    by_title[norm] = p
    deduped = list(by_title.values())

    high = sum(1 for p in deduped if p["confidence"] == "high")
    print(f"[dblp] Found {len(deduped)} publications ({high} high-confidence, {len(deduped)-high} low — see KNOWN_COAUTHORS)")
    return deduped


# ---------- Local asset auto-linker ----------
def _slugify(text):
    """Lowercase, alphanumeric-only, single-spaced. Used for fuzzy matching."""
    s = re.sub(r"[^a-z0-9]+", "", (text or "").lower())
    return s


def _filename_keys(stem):
    """A filename like 'inet-2022', '2022_inet', or 'inet(2022)' all reduce to ['…2022', 'inet']."""
    raw = (stem or "").lower()
    # Slugify the original
    keys = [_slugify(raw)]
    # Strip a 4-digit year wherever it sits (with or without separators), then re-slugify.
    stripped = re.sub(r"(?:^|[\s\-_.()])(19|20)\d{2}(?:$|[\s\-_.()])", " ", raw).strip()
    if stripped and stripped != raw:
        s2 = _slugify(stripped)
        if s2 and s2 not in keys and len(s2) >= 3:
            keys.append(s2)
    return keys


def link_local_assets(publications):
    """Scan assets/<folder>/* and link each file to a publication by fuzzy
    title match. Files override URLs from manual overrides only if no URL
    is set yet (manual JSON wins).

    Files are linked as relative paths (e.g. 'assets/pdf/inet.pdf') so they
    work over the local file:// protocol AND the http server.
    """
    if not ASSETS_DIR.exists():
        return 0

    # Build title-slug -> publication map
    title_index = []  # list of (slug, pub) — we want longest-match
    for p in publications:
        slug = _slugify(p.get("title", ""))
        if slug:
            title_index.append((slug, p))

    def find_best_pub(stem):
        """Return the publication whose title-slug most-specifically matches the filename.

        Requires (a) the filename slug to be at least 4 chars, (b) the matching key to
        cover at least 25% of the filename slug, and (c) no other publication match the
        same key length. Logs a WARN and returns None on ambiguity, so the asset is
        skipped rather than silently bound to the wrong paper.
        """
        candidates = []  # (keylen, key, pub)
        best_keylen = 0
        for key in _filename_keys(stem):
            if not key or len(key) < 4:
                continue
            for slug, pub in title_index:
                if key in slug and len(key) >= best_keylen:
                    if len(key) > best_keylen:
                        candidates = []
                        best_keylen = len(key)
                    candidates.append((len(key), key, pub))
        if not candidates:
            return None
        # Specificity guard: reject very short matches against a long filename
        slug_len = len(_slugify(stem))
        if slug_len and (best_keylen / slug_len) < 0.25:
            print(f"[assets] WARN: '{stem}' match '{candidates[0][1]}' too generic "
                  f"({best_keylen}/{slug_len} chars) — rename more specifically; skipping")
            return None
        unique_titles = {p.get("title", "") for _, _, p in candidates}
        if len(unique_titles) > 1:
            print(f"[assets] WARN: '{stem}' is ambiguous between "
                  f"{sorted(unique_titles)} — rename more specifically; skipping")
            return None
        return candidates[0][2]

    def is_safe_asset(f):
        """Reject filenames whose characters could break HTML attributes or shell
        invocations, and reject symlinks that escape ASSETS_DIR. Returns True if
        the file is safe to embed in JSON/HTML."""
        if not re.match(r"^[A-Za-z0-9._\-+ ()]+$", f.name):
            print(f"[assets] WARN: skipping '{f.name}' — non-ASCII or special "
                  f"characters in filename (allowed: letters, digits, ._-+ space parens)")
            return False
        try:
            resolved = f.resolve()
            if ASSETS_DIR.resolve() not in resolved.parents:
                print(f"[assets] WARN: skipping '{f.name}' — symlink escapes assets/ ({resolved})")
                return False
        except Exception as e:
            print(f"[assets] WARN: skipping '{f.name}' — could not resolve: {e}")
            return False
        return True

    linked_count = 0

    # URL-style assets: store relative path
    for field, (folder, exts) in ASSET_FOLDERS_URL.items():
        d = ASSETS_DIR / folder
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.name.startswith(".") or f.name.lower() == "readme.md":
                continue
            if f.suffix.lower() not in exts:
                continue
            if not is_safe_asset(f):
                continue
            best_pub = find_best_pub(f.stem)
            if best_pub:
                rel = f"assets/{folder}/{f.name}"
                if not best_pub.get(field) or str(best_pub.get(field, "")).startswith("assets/"):
                    best_pub[field] = rel
                    linked_count += 1
            else:
                print(f"[assets] WARN: '{f.name}' didn't match any paper")

    # Text-content assets: read the file body into the field
    for field, (folder, exts) in ASSET_FOLDERS_TEXT.items():
        d = ASSETS_DIR / folder
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.name.startswith(".") or f.name.lower() == "readme.md":
                continue
            if f.suffix.lower() not in exts:
                continue
            if not is_safe_asset(f):
                continue
            best_pub = find_best_pub(f.stem)
            if best_pub:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace").strip()
                    if content:
                        best_pub[field] = content
                        linked_count += 1
                except Exception as e:
                    print(f"[assets] WARN: failed to read '{f.name}': {e}")
            else:
                print(f"[assets] WARN: '{f.name}' didn't match any paper")

    return linked_count


def find_local_photo():
    """Return relative path to a profile photo if one exists in assets/photo/."""
    d = ASSETS_DIR / "photo"
    if not d.exists():
        return None
    for ext in [".jpg", ".jpeg", ".png", ".webp"]:
        for f in sorted(d.iterdir()):
            if f.suffix.lower() == ext and not f.name.startswith("."):
                return f"assets/photo/{f.name}"
    return None


def find_local_cv():
    """Return relative path to a CV PDF if one exists in assets/cv/."""
    d = ASSETS_DIR / "cv"
    if not d.exists():
        return None
    for f in sorted(d.iterdir()):
        if f.suffix.lower() == ".pdf" and not f.name.startswith("."):
            return f"assets/cv/{f.name}"
    return None


# ---------- DOI publisher-page scraper ----------
def crawl_doi_for_pdf(doi):
    """Follow a DOI URL to the publisher page and extract PDF link from
    Highwire-style <meta name="citation_pdf_url"> tag.
    Works for: Springer, Frontiers, Nature, PLOS, BMC, JCST, FITEE — i.e. any
    publisher that follows the academic citation_pdf_url convention.
    Does NOT work for: IEEE Xplore, ACM DL, ScienceDirect, Sage (paywalled / 403).
    """
    if not doi:
        return None
    url = doi if doi.startswith("http") else f"https://doi.org/{doi}"
    try:
        req = Request(url, headers={
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        resp = urlopen(req, timeout=20)
        body = resp.read().decode("utf-8", errors="replace")

        # Highwire-style citation_pdf_url meta tag
        for pattern in [
            r'<meta[^>]*name=["\']citation_pdf_url["\'][^>]*content=["\']([^"\']+)',
            r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*name=["\']citation_pdf_url["\']',
        ]:
            m = re.search(pattern, body, re.IGNORECASE)
            if m:
                return m.group(1)
    except HTTPError as e:
        if e.code != 404:
            print(f"[doi-crawl] WARN: {url} HTTP {e.code}")
    except URLError as e:
        print(f"[doi-crawl] WARN: {url} unreachable: {e.reason}")
    except Exception as e:
        print(f"[doi-crawl] WARN: {url} parse failed: {e}")
    return None


# ---------- Persistent PDF cache ----------
def load_cached_publications():
    """Load previous publications.json so we can preserve already-found PDFs/citations."""
    if not OUTPUT_FILE.exists():
        return {}
    try:
        with open(OUTPUT_FILE) as f:
            data = json.load(f)
        cache = {}
        for p in data.get("publications", []):
            # Index by normalized title and by DOI
            norm = re.sub(r"[^\w\s]", "", (p.get("title") or "").lower())
            norm = re.sub(r"\s+", " ", norm).strip()
            if norm:
                cache[norm] = p
            doi = (p.get("doi") or "").lower().strip()
            if doi:
                cache[doi] = p
        return cache
    except Exception:
        return {}


def apply_cache(publications, cache):
    """For each publication, restore PDF URL and citation count from cache when missing."""
    if not cache:
        return 0
    restored = 0
    for p in publications:
        norm = re.sub(r"[^\w\s]", "", (p.get("title") or "").lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        cached = cache.get(norm) or cache.get((p.get("doi") or "").lower().strip())
        if not cached:
            continue
        touched = False
        for field in ["pdf_url", "video_url", "code_url", "project_url"]:
            if not p.get(field) and cached.get(field):
                p[field] = cached[field]
                touched = True
        if not p.get("citations") and cached.get("citations"):
            p["citations"] = cached["citations"]
            touched = True
        if touched:
            restored += 1
    return restored


# ---------- OpenAlex enrichment (PDF + citations, no API key needed) ----------
def enrich_with_openalex(publications, contact_email=CONTACT_EMAIL):
    """For each publication, query OpenAlex by DOI (preferred) or title to find:
       - open-access PDF URL (often arXiv)
       - cited_by_count
    OpenAlex is free, no API key, and very reliable.
    """
    headers = {"User-Agent": f"academic-homepage/1.0 (mailto:{contact_email})"}
    enriched = 0
    pdf_found = 0

    for i, pub in enumerate(publications):
        # Skip if we already have both PDF and a citation count (cached from prior run)
        had_pdf = bool(pub.get("pdf_url"))
        if had_pdf and pub.get("citations", 0) > 0:
            continue

        candidates = []

        # Strategy A: direct DOI lookup
        doi = pub.get("doi", "")
        if doi:
            clean_doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi).strip()
            try:
                url = f"https://api.openalex.org/works/doi:{urllib.parse.quote(clean_doi, safe='/.')}"
                req = Request(url, headers=headers)
                data = json.load(urlopen(req, timeout=15))
                candidates.append(data)
            except Exception as e:
                print(f"[openalex] WARN: DOI lookup {clean_doi} failed: {e}")

        # Strategy B: search by title
        if pub.get("title"):
            try:
                title_q = pub["title"][:200]
                url = f"https://api.openalex.org/works?search={urllib.parse.quote(title_q)}&per_page=5"
                req = Request(url, headers=headers)
                data = json.load(urlopen(req, timeout=15))
                target = pub["title"].lower().strip()
                target_year = str(pub.get("year") or "").strip()
                for w in data.get("results", []):
                    t = (w.get("title") or "").lower().strip()
                    if not t or len(t) < 10 or len(target) < 10:
                        continue
                    # Accept exact match, or a shared prefix that covers most of the
                    # shorter title and (when both have years) the years agree.
                    same_prefix = (
                        t == target
                        or (min(len(t), len(target)) >= 40 and t[:40] == target[:40])
                    )
                    if not same_prefix:
                        continue
                    w_year = str((w.get("publication_year") or "")).strip()
                    if target_year and w_year and target_year != w_year:
                        # Year mismatch on a prefix-only match → likely a different paper
                        continue
                    candidates.append(w)
            except Exception as e:
                print(f"[openalex] WARN: title search for {pub['title'][:50]!r} failed: {e}")

        # Pick best PDF + max citation count from all candidates
        best_pdf = None
        max_cites = pub.get("citations", 0)
        oa_url = None
        for w in candidates:
            cites = w.get("cited_by_count", 0)
            if cites > max_cites:
                max_cites = cites
            if not oa_url:
                oa_url = (w.get("open_access") or {}).get("oa_url")
            for path in [
                (w.get("best_oa_location") or {}).get("pdf_url"),
                (w.get("primary_location") or {}).get("pdf_url"),
            ]:
                if path and not best_pdf:
                    best_pdf = path
            for loc in (w.get("locations") or []):
                pdf = loc.get("pdf_url")
                if pdf and not best_pdf:
                    best_pdf = pdf

        if max_cites > pub.get("citations", 0):
            pub["citations"] = max_cites
            enriched += 1
        if best_pdf and not had_pdf:
            pub["pdf_url"] = best_pdf
            pdf_found += 1
        elif oa_url and not had_pdf and not pub.get("pub_url"):
            pub["pub_url"] = oa_url

        # Be polite to OpenAlex (no rate limit but ~10 req/s recommended)
        time.sleep(0.15)

        if (i + 1) % 5 == 0:
            print(f"[openalex] processed {i+1}/{len(publications)}")

    print(f"[openalex] enriched {enriched} citation counts, found {pdf_found} new PDFs")


# ---------- Google Scholar enrichment (citation counts) ----------
def enrich_with_scholar(publications, timeout_sec=60, use_proxy=False):
    """Try to add citation counts from Google Scholar. Best-effort."""
    try:
        from scholarly import scholarly, ProxyGenerator
    except ImportError:
        print("[scholar] scholarly not installed, skipping enrichment")
        return None

    print(f"[scholar] Attempting to fetch profile {SCHOLAR_ID} (timeout {timeout_sec}s)")
    start = time.time()

    try:
        # FreeProxies probes the network for >1min and is opt-in (--use-proxy).
        # Without it the call is fast but may be CAPTCHA-blocked.
        if use_proxy:
            try:
                pg = ProxyGenerator()
                if pg.FreeProxies():
                    scholarly.use_proxy(pg)
                    print("[scholar] Using free proxy")
            except Exception as e:
                print(f"[scholar] FreeProxies failed: {e}")

        author = scholarly.search_author_id(SCHOLAR_ID)
        if time.time() - start > timeout_sec:
            raise TimeoutError("Scholar lookup exceeded timeout")

        author = scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])

        # Build title -> citation count map
        title_to_cites = {}
        for pub in author.get("publications", []):
            bib = pub.get("bib", {})
            t = bib.get("title", "").lower().strip()
            if t:
                title_to_cites[t] = pub.get("num_citations", 0)

        # Merge into publications
        matched = 0
        for pub in publications:
            t = pub["title"].lower().strip()
            if t in title_to_cites:
                pub["citations"] = title_to_cites[t]
                matched += 1

        author_info = {
            "citedby": author.get("citedby", 0),
            "hindex": author.get("hindex", 0),
            "i10index": author.get("i10index", 0),
            "citedby_history": author.get("cites_per_year", {}),
            "interests": author.get("interests", []),
            "affiliation": author.get("affiliation", ""),
            "photo_url": author.get("url_picture", ""),
        }
        print(f"[scholar] Enriched {matched}/{len(publications)} publications, h-index={author_info['hindex']}")
        return author_info
    except Exception as e:
        print(f"[scholar] Enrichment failed: {e}")
        return None


# ---------- Direct HTTP scrape of Google Scholar (fallback for citation indices) ----------
def scrape_scholar_indices():
    """Try to grab h-index, i10-index, total citations from Scholar profile HTML."""
    url = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
    print(f"[scholar-http] Fetching {url}")
    try:
        body, status = http_get(url, timeout=15)
        if status != 200:
            return None
        if "CAPTCHA" in body or "unusual traffic" in body:
            print("[scholar-http] Blocked by CAPTCHA")
            return None
        nums = re.findall(r'class="gsc_rsb_std"[^>]*>(\d+)', body)
        if len(nums) >= 6:
            return {
                "citedby": int(nums[0]),
                "hindex": int(nums[2]),
                "i10index": int(nums[4]),
            }
        print(f"[scholar-http] WARN: expected ≥6 stat numbers, got {len(nums)} — Scholar layout may have changed")
    except Exception as e:
        print(f"[scholar-http] Failed: {e}")
    return None


# ---------- Manual overrides ----------
def merge_manual_overrides(publications, manual_data):
    if not manual_data:
        # Default: drop low-confidence (likely-wrong-person) papers when no manual file exists
        return [p for p in publications if p.get("confidence") != "low"]

    # Friendly schema check — typos here used to produce opaque AttributeErrors
    if not isinstance(manual_data, dict):
        raise TypeError(f"publications_manual.json must be an object, got {type(manual_data).__name__}")
    for key, expected in [("publications", list), ("exclude", list),
                          ("include_low_confidence", list), ("author", dict)]:
        val = manual_data.get(key)
        if val is not None and not isinstance(val, expected):
            raise TypeError(f"publications_manual.json: '{key}' must be {expected.__name__}, "
                            f"got {type(val).__name__}")

    # 1. Filter by confidence + manual include/exclude
    excludes = {t.lower().strip() for t in manual_data.get("exclude", [])}
    includes = {t.lower().strip() for t in manual_data.get("include_low_confidence", [])}
    keep_all_low = manual_data.get("keep_all_low_confidence", False)

    # Warn on suspiciously short keys that would substring-match many papers.
    for ex in excludes:
        if len(ex) < 12:
            print(f"[manual] WARN: exclude key {ex!r} is short ({len(ex)} chars) — "
                  f"will substring-match every paper containing it; use a longer phrase to avoid mass deletion")
    for inc in includes:
        if len(inc) < 12:
            print(f"[manual] WARN: include_low_confidence key {inc!r} is short ({len(inc)} chars) — "
                  f"will match every paper containing it")

    exclude_hits = {ex: 0 for ex in excludes}
    include_hits = {inc: 0 for inc in includes}
    filtered = []
    for p in publications:
        title_l = p["title"].lower().strip()
        # Explicit exclude wins
        matched_ex = next((ex for ex in excludes if title_l.startswith(ex) or ex in title_l), None)
        if matched_ex:
            exclude_hits[matched_ex] += 1
            continue
        # Drop low-confidence unless explicitly opted in
        if p.get("confidence") == "low" and not keep_all_low:
            matched_inc = next((inc for inc in includes if inc in title_l or title_l.startswith(inc)), None)
            if not matched_inc:
                continue
            include_hits[matched_inc] += 1
        filtered.append(p)
    for ex, n in exclude_hits.items():
        if n > 1:
            print(f"[manual] WARN: exclude {ex!r} dropped {n} papers — was that intentional?")
    for inc, n in include_hits.items():
        if n > 1:
            print(f"[manual] WARN: include_low_confidence {inc!r} matched {n} low-confidence papers")
    publications = filtered

    by_title = {}
    by_doi = {}
    for entry in manual_data.get("publications", []):
        t = (entry.get("title") or "").lower().strip()
        if t:
            by_title[t] = entry
        d = (entry.get("doi") or "").lower().strip()
        if d:
            by_doi[d] = entry

    extra_titles = set(by_title.keys())
    for pub in publications:
        keys = [pub["title"].lower().strip(), (pub.get("doi") or "").lower().strip()]
        match = None
        for k in keys:
            if k and k in by_title:
                match = by_title[k]
                extra_titles.discard(k)
                break
            if k and k in by_doi:
                match = by_doi[k]
                extra_titles.discard(match.get("title", "").lower().strip())
                break
        if match:
            for field in ["pdf_url", "video_url", "project_url", "code_url",
                          "teaser_url", "slides_url", "appendix_url",
                          "doi", "pub_url", "venue", "year", "authors",
                          "author_position", "title_zh", "award", "tldr", "abstract",
                          "type", "key"]:
                if match.get(field):
                    pub[field] = match[field]
            if match.get("citations") is not None and pub["citations"] == 0:
                pub["citations"] = match["citations"]
            if match.get("confidence"):
                pub["confidence"] = match["confidence"]

    # Add purely-manual publications that weren't in DBLP
    for t in extra_titles:
        if t.startswith("example "):
            continue
        m = by_title[t]
        # Auto-detect first-author for manually-added papers too
        authors = m.get("authors", "")
        author_position = m.get("author_position")
        if not author_position and authors:
            parts = [s.strip() for s in authors.split(",")]
            self_aliases_lower = {a.lower() for a in AUTHOR_ALIASES}
            for idx, a in enumerate(parts):
                if a.lower() in self_aliases_lower or "韩东明" in a:
                    if idx == 0:
                        author_position = "first"
                    elif idx == len(parts) - 1 and len(parts) >= 3:
                        author_position = "last"
                    else:
                        author_position = "middle"
                    break
        pub = {
            "title": m.get("title", ""),
            "title_zh": m.get("title_zh", ""),
            "authors": authors,
            "year": str(m.get("year", "")),
            "venue": m.get("venue", ""),
            "citations": m.get("citations", 0),
            "scholar_url": m.get("scholar_url", ""),
            "pub_url": m.get("pub_url", ""),
            "pdf_url": m.get("pdf_url", ""),
            "doi": m.get("doi", ""),
            "video_url": m.get("video_url", ""),
            "project_url": m.get("project_url", ""),
            "code_url": m.get("code_url", ""),
            "teaser_url": m.get("teaser_url", ""),
            "slides_url": m.get("slides_url", ""),
            "appendix_url": m.get("appendix_url", ""),
            "award": m.get("award", ""),
            "tldr": m.get("tldr", ""),
            "abstract": m.get("abstract", ""),
            "confidence": m.get("confidence", "high"),
            "author_position": author_position or "",
            "type": "manual",
        }
        publications.append(pub)
    return publications


def load_manual():
    if MANUAL_FILE.exists():
        with open(MANUAL_FILE) as f:
            return json.load(f)
    return None


# ---------- Main ----------
def main():
    parser = argparse.ArgumentParser(description="Fetch publications for academic homepage")
    parser.add_argument("--use-cache", action="store_true",
                        help="Skip remote fetching; only re-merge manual overrides into existing publications.json")
    parser.add_argument("--no-scholar", action="store_true",
                        help="Skip Google Scholar enrichment (DBLP only)")
    parser.add_argument("--no-openalex", action="store_true",
                        help="Skip OpenAlex enrichment AND DOI publisher-page crawl")
    parser.add_argument("--use-proxy", action="store_true",
                        help="Let scholarly probe FreeProxies (slow; only useful if Scholar is rate-limiting)")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    manual_data = load_manual()

    if args.use_cache and OUTPUT_FILE.exists():
        with open(OUTPUT_FILE) as f:
            data = json.load(f)
        data.setdefault("author", {})
        data.setdefault("publications", [])
        data["publications"] = merge_manual_overrides(data["publications"], manual_data)
        n_linked = link_local_assets(data["publications"])
        local_photo = find_local_photo()
        if local_photo:
            data["author"]["photo_url"] = local_photo
        local_cv = find_local_cv()
        if local_cv:
            data["author"]["cv_url"] = local_cv
        # Apply manual author overrides (affiliation, interests, etc.)
        if manual_data and manual_data.get("author"):
            for k, v in manual_data["author"].items():
                if k.startswith("_"):
                    continue
                if v:
                    data["author"][k] = v
        data["publications"].sort(
            key=lambda p: (int(p.get("year") or 0), p.get("citations", 0)), reverse=True
        )
        # Recompute author indices from the (possibly-edited) per-paper citations.
        # Take max with existing values so we don't clobber a higher Scholar-sourced
        # h-index with a lower locally-derived one.
        cites_sorted = sorted((p.get("citations", 0) for p in data["publications"]), reverse=True)
        h = 0
        for i, c in enumerate(cites_sorted, 1):
            if c >= i:
                h = i
            else:
                break
        derived = {
            "hindex": h,
            "i10index": sum(1 for c in cites_sorted if c >= 10),
            "citedby": sum(cites_sorted),
        }
        for k, v in derived.items():
            if v > int(data["author"].get(k) or 0):
                data["author"][k] = v
        with open(OUTPUT_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[cache] Re-merged manual overrides + linked {n_linked} local asset(s); "
              f"derived h={derived['hindex']} i10={derived['i10index']} → {OUTPUT_FILE}")
        return

    # 0. Load persistent cache so we don't re-fetch known PDFs
    cache = load_cached_publications()
    if cache:
        unique = len({id(v) for v in cache.values()})
        print(f"[cache] Loaded {unique} cached entries (will preserve known PDFs)")

    # 1. Fetch publications from DBLP
    try:
        publications = fetch_from_dblp()
    except Exception as e:
        print(f"[ERROR] DBLP fetch failed: {e}")
        publications = []
        if OUTPUT_FILE.exists():
            with open(OUTPUT_FILE) as f:
                publications = json.load(f).get("publications", [])
            print(f"[fallback] Using {len(publications)} cached publications")

    # 1b. Restore cached PDFs / citations / video / code URLs
    if cache:
        restored = apply_cache(publications, cache)
        already_pdf = sum(1 for p in publications if p.get("pdf_url"))
        print(f"[cache] Restored data for {restored} pubs; {already_pdf}/{len(publications)} now have PDFs")

    # 2. Crawl DOI publisher pages for any paper still missing a PDF
    needs_pdf = [p for p in publications if not p.get("pdf_url") and p.get("doi")]
    if needs_pdf and not args.no_openalex:
        print(f"[doi-crawl] Looking up {len(needs_pdf)} DOI pages for citation_pdf_url...")
        found = 0
        for i, p in enumerate(needs_pdf):
            pdf = crawl_doi_for_pdf(p["doi"])
            if pdf:
                p["pdf_url"] = pdf
                found += 1
            time.sleep(random.uniform(0.5, 1.5))  # be polite
            if (i + 1) % 5 == 0:
                print(f"[doi-crawl] processed {i+1}/{len(needs_pdf)}, {found} PDFs found so far")
        print(f"[doi-crawl] Found {found}/{len(needs_pdf)} PDFs from publisher pages")

    # 3. Enrich with OpenAlex (PDFs + citations) — for remaining papers
    if publications and not args.no_openalex:
        try:
            enrich_with_openalex(publications)
        except Exception as e:
            print(f"[openalex] failed: {e}")

    # 3. Try Google Scholar (h-index, total citation count for author)
    author_extra = None
    if not args.no_scholar:
        author_extra = enrich_with_scholar(publications, timeout_sec=45, use_proxy=args.use_proxy)

    # 3b. Direct HTTP fallback for citation indices
    indices = None
    if author_extra is None:
        indices = scrape_scholar_indices()

    # 3c. If we still don't have h-index, derive from publication citation counts
    if author_extra is None and indices is None and publications:
        cites_sorted = sorted((p.get("citations", 0) for p in publications), reverse=True)
        h = 0
        for i, c in enumerate(cites_sorted, 1):
            if c >= i:
                h = i
            else:
                break
        i10 = sum(1 for c in cites_sorted if c >= 10)
        total = sum(cites_sorted)
        indices = {"hindex": h, "i10index": i10, "citedby": total}
        print(f"[derived] computed h-index={h}, i10={i10}, total citations={total} from per-paper counts")

    # 4. Merge manual overrides
    publications = merge_manual_overrides(publications, manual_data)

    # 5. Auto-link local files in assets/{pdf,video,appendix,slides}/
    n_linked = link_local_assets(publications)
    if n_linked:
        print(f"[assets] Linked {n_linked} local file(s) to publications")

    # 4. Sort newest-first, then by citations
    publications.sort(key=lambda p: (int(p.get("year") or 0), p.get("citations", 0)), reverse=True)

    # 5. Build author info
    author_info = {
        "name": AUTHOR_NAME,
        "name_zh": "韩东明",
        "affiliation": DEFAULT_AFFILIATION,
        "interests": list(DEFAULT_INTERESTS),
        "photo_url": "",
        "citedby": 0,
        "hindex": 0,
        "i10index": 0,
        "citedby_history": {},
        "scholar_url": f"https://scholar.google.com/citations?user={SCHOLAR_ID}",
        "dblp_url": f"https://dblp.org/pid/{DBLP_PID}.html",
        "github_url": "https://github.com/woaiwodib107",
        "email": CONTACT_EMAIL,
    }

    if author_extra:
        for k, v in author_extra.items():
            if v:
                author_info[k] = v
    elif indices:
        author_info.update(indices)

    # Floor the headline metrics against whatever was previously saved. A blocked or
    # CAPTCHA'd Scholar run falls back to values derived from local per-paper counts,
    # which are always lower — without this, a bad run silently rewrites 325 citations
    # down to ~166. Mirrors the same guard on the --use-cache path.
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, encoding="utf-8") as fh:
                prev = json.load(fh).get("author", {})
            for k in ("citedby", "hindex", "i10index"):
                if int(prev.get(k) or 0) > int(author_info.get(k) or 0):
                    print(f"[metrics] keeping previous {k}={prev[k]} "
                          f"(this run derived {author_info.get(k)})")
                    author_info[k] = prev[k]
        except (OSError, ValueError) as e:
            print(f"[metrics] WARN: could not read previous metrics: {e}")

    # Allow manual overrides for author info too
    if manual_data and manual_data.get("author"):
        for k, v in manual_data["author"].items():
            if k.startswith("_"):
                continue
            if v:
                author_info[k] = v

    # Local profile photo trumps remote URL
    local_photo = find_local_photo()
    if local_photo:
        author_info["photo_url"] = local_photo
    # Local CV
    local_cv = find_local_cv()
    if local_cv:
        author_info["cv_url"] = local_cv

    output = {
        "author": author_info,
        "publications": publications,
        "last_updated": time.strftime("%Y-%m-%d %H:%M:%S %Z") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "DBLP" + (" + Google Scholar" if author_extra else ""),
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n[done] Saved {len(publications)} publications to {OUTPUT_FILE}")
    print(f"  Author: {author_info['name']}")
    print(f"  Citations: {author_info.get('citedby', 'unknown')}")
    print(f"  H-index: {author_info.get('hindex', 'unknown')}")
    print(f"  Last updated: {output['last_updated']}")


if __name__ == "__main__":
    main()
