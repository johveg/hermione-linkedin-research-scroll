#!/usr/bin/env python3
"""Build a durable, paginated public LinkedIn research scroll.

Only public metadata, post text, research conclusions, and archived post media are
published. The generated posts.json is a durable public index: a later partial
intake source may add or refresh articles but must never remove an already
published filing.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

DEFAULT_SOURCE = Path("/home/hermoine/agent-research-linkedin-source/data/posts")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "index.html"
DATA = ROOT / "posts.json"
MANIFEST = ROOT / "manifest.json"
ASSETS = ROOT / "assets" / "posts"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

PUBLIC_SECTION_TERMS = (
    "post summary", "visible post summary", "core post claim", "what the post claims",
    "what the post says", "what it is", "linkedin-visible thesis", "assessment",
    "claim and assessment", "primary-source quick pass", "book relevance", "hermione relevance",
    "evidence strength", "evidence assessment", "evidence and limitations", "evidence caveats",
    "content assessment", "candidate book claim", "implication for hermione", "caveats",
    "limitations", "practical adoption path", "operational trade-off", "security & privacy caveats",
    "important caveats", "media summary",
)
EXCLUDED_SECTION_TERMS = (
    "capture", "authenticated", "comment", "discussion", "safely captured", "media and comments",
    "visible media", "publication status", "push preflight", "archive",
)
PUBLIC_FIELDS = (
    "activity_id", "title", "headline", "author", "author_url", "canonical_url",
    "published_at", "filed_at", "post_text", "images",
)


def clean_text(value: object) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").replace("\x00", "").splitlines()).strip()


def title_from_summary(summary: str, fallback: str) -> str:
    for line in summary.splitlines():
        if line.startswith("# "):
            return clean_text(line[2:])
    return fallback


def public_summary(text: str) -> str:
    """Retain research conclusions, not capture mechanics or third-party comments."""
    kept: list[str] = []
    include = False
    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip().lower()
            include = any(term in heading for term in PUBLIC_SECTION_TERMS) and not any(
                term in heading for term in EXCLUDED_SECTION_TERMS
            )
        if include:
            kept.append(line)
    return "\n".join(kept).strip()


def markdown_to_html(text: str) -> str:
    """Small, safe renderer for the limited intake-summary Markdown subset."""
    out: list[str] = []
    paragraph: list[str] = []
    in_list = False

    def inline(value: str) -> str:
        value = html.escape(value, quote=True)
        value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
        value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
        value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
        return value

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + " ".join(inline(x) for x in paragraph) + "</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            if len(heading.group(1)) > 1:
                out.append("<h3>" + inline(heading.group(2)) + "</h3>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            close_list()
            out.append("<blockquote>" + inline(line[2:]) + "</blockquote>")
            continue
        if line.startswith("- "):
            flush_paragraph()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + inline(line[2:]) + "</li>")
            continue
        paragraph.append(line)
    flush_paragraph()
    close_list()
    return "\n".join(out)


def copy_media(post_dir: Path, activity_id: str) -> list[str]:
    source = post_dir / "media"
    if not source.exists():
        return []
    target = ASSETS / activity_id
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for media in sorted(source.iterdir()):
        if not media.is_file() or media.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", media.name)
        shutil.copy2(media, target / safe_name)
        copied.append(f"assets/posts/{activity_id}/{safe_name}")
    return copied


def collect_posts(source: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for post_dir in source.iterdir():
        if not post_dir.is_dir() or post_dir.name.startswith(("pending-", "pulse-")):
            continue
        metadata_path = post_dir / "metadata.json"
        post_path = post_dir / "post.txt"
        if not metadata_path.exists() or not post_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        activity_id = clean_text(metadata.get("activity_id"))
        if not activity_id:
            continue
        post = metadata.get("post") or {}
        author = metadata.get("author") or {}
        summary_path = post_dir / "intake-summary.md"
        raw_summary = summary_path.read_text(encoding="utf-8", errors="replace") if summary_path.exists() else ""
        headline = clean_text(post.get("headline")) or clean_text(post_path.read_text(encoding="utf-8", errors="replace").splitlines()[0] if post_path.read_text(encoding="utf-8", errors="replace") else "Untitled archive")
        records.append({
            "activity_id": activity_id,
            "title": title_from_summary(raw_summary, headline),
            "headline": headline,
            "author": clean_text(author.get("name")) or "LinkedIn author",
            "author_url": clean_text(author.get("profile_url")),
            "canonical_url": clean_text(metadata.get("canonical_url")) or clean_text(metadata.get("input_url")),
            "published_at": clean_text(post.get("published_at")),
            "filed_at": clean_text(metadata.get("fetched_at")) or clean_text(post.get("published_at")),
            "post_text": clean_text(post_path.read_text(encoding="utf-8", errors="replace")),
            "summary": public_summary(raw_summary),
            "images": copy_media(post_dir, activity_id),
        })
    return records


def load_published_records() -> list[dict[str, object]]:
    """Read the prior public index, treating it as an append-only safety net."""
    if not DATA.is_file():
        return []
    try:
        payload = json.loads(DATA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    posts = payload.get("posts") if isinstance(payload, dict) else None
    if not isinstance(posts, list):
        return []
    return [item for item in posts if isinstance(item, dict) and clean_text(item.get("activity_id"))]


def sort_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(records, key=lambda r: (str(r.get("filed_at", "")), str(r.get("published_at", ""))), reverse=True)


def merge_records(source_records: list[dict[str, object]], published_records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Keep all prior public filings; current intake records refresh matching IDs."""
    merged = {clean_text(item.get("activity_id")): item for item in published_records if clean_text(item.get("activity_id"))}
    merged.update({clean_text(item.get("activity_id")): item for item in source_records if clean_text(item.get("activity_id"))})
    return sort_records(list(merged.values()))


def public_payload(records: list[dict[str, object]]) -> dict[str, object]:
    posts: list[dict[str, object]] = []
    total = len(records)
    for index, record in enumerate(records):
        item = {field: record.get(field, [] if field == "images" else "") for field in PUBLIC_FIELDS}
        item["images"] = [clean_text(image) for image in item["images"] if clean_text(image)] if isinstance(item["images"], list) else []
        item["summary_html"] = clean_text(record.get("summary_html")) or markdown_to_html(clean_text(record.get("summary")))
        item["number"] = total - index
        posts.append(item)
    return {"count": total, "posts": posts}


def build_page(count: int) -> str:
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A chronological, research-backed scroll of LinkedIn articles filed by Hermione Hermes.">
  <title>Hermione LinkedIn Research Scroll</title>
  <style>
    :root {{ --ink:#172033; --muted:#5d677c; --paper:#fffdf8; --wash:#edf4f2; --line:#d8dfdf; --accent:#126b64; --accent-pale:#d8eee9; --serif:Georgia,'Times New Roman',serif; --sans:Inter,ui-sans-serif,system-ui,sans-serif; }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; color:var(--ink); background:var(--paper); font-family:var(--sans); line-height:1.62; }}
    a {{ color:var(--accent); text-decoration-thickness:1px; text-underline-offset:3px; }}
    .masthead {{ padding:clamp(3rem,8vw,7rem) max(1.25rem,calc((100vw - 1060px)/2)); background:linear-gradient(130deg,#123e46,#1e6b64 70%,#5ba99d); color:white; }} .masthead-inner {{ max-width:900px; }} .kicker,.eyebrow {{ margin:0; text-transform:uppercase; letter-spacing:.12em; font-size:.73rem; font-weight:750; }} .masthead h1 {{ max-width:750px; font-family:var(--serif); font-size:clamp(2.5rem,6vw,5.4rem); line-height:.98; font-weight:500; margin:.7rem 0 1.2rem; }} .masthead p:not(.kicker) {{ max-width:690px; margin:0; font-size:1.05rem; color:#e1f5ef; }}
    .stats {{ display:flex; flex-wrap:wrap; gap:.75rem; margin-top:1.8rem; }} .stats span {{ padding:.45rem .7rem; border:1px solid #91c9bf; border-radius:999px; font-size:.84rem; }} main {{ max-width:1060px; margin:auto; padding:clamp(2rem,5vw,5rem) 1.25rem 7rem; }} .note {{ max-width:780px; padding:1rem 1.2rem; margin:0 0 3rem; background:var(--wash); border-left:4px solid var(--accent); color:#354b50; font-size:.93rem; }}
    .entry {{ display:grid; grid-template-columns:76px minmax(0,1fr); gap:1.2rem; border-top:1px solid var(--line); padding:3.2rem 0; }} .entry-number {{ color:var(--accent); font-family:var(--serif); font-size:1.85rem; line-height:1; padding-top:.45rem; }} .entry-body {{ max-width:810px; }} .eyebrow {{ color:var(--muted); }} h2 {{ font-family:var(--serif); font-size:clamp(1.75rem,3.6vw,3rem); line-height:1.08; font-weight:500; margin:.45rem 0 .8rem; }} .byline {{ margin:0 0 1.2rem; color:var(--muted); font-size:.92rem; }} .original-link {{ margin-left:.55rem; white-space:nowrap; }} .headline {{ font-family:var(--serif); font-size:1.2rem; line-height:1.45; margin:0 0 1.4rem; }}
    .media {{ display:grid; gap:1rem; margin:1.3rem 0 2rem; }} .media img {{ max-width:100%; max-height:650px; border:1px solid var(--line); border-radius:5px; background:#f5f5f5; object-fit:contain; }} .research {{ font-size:1rem; }} .research h3 {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.1em; color:var(--accent); margin:2rem 0 .55rem; }} .research p {{ margin:.7rem 0; }} .research ul {{ padding-left:1.25rem; }} blockquote {{ margin:1.1rem 0; padding:.8rem 1rem; border-left:3px solid var(--accent); background:#f5faf8; font-family:var(--serif); font-size:1.08rem; }} code {{ font-size:.9em; background:#eef1f1; padding:.1em .25em; }} details {{ margin-top:1.7rem; border-top:1px solid var(--line); padding-top:.7rem; }} summary {{ cursor:pointer; color:var(--accent); font-weight:700; }} .post-text {{ white-space:pre-wrap; margin-top:.8rem; color:#445; font-size:.92rem; }}
    .load-area {{ text-align:center; padding:2rem 0 0; }} #load-more {{ cursor:pointer; color:white; background:var(--accent); border:0; padding:.8rem 1.1rem; font:inherit; font-weight:700; border-radius:4px; }} #load-more:hover,#load-more:focus {{ background:#0c504b; }} #progress {{ color:var(--muted); font-size:.9rem; }} footer {{ border-top:1px solid var(--line); padding:2rem 0 0; color:var(--muted); font-size:.88rem; }}
    @media (max-width:620px) {{ .entry {{ grid-template-columns:1fr; gap:.5rem; }} .entry-number {{ font-size:1.2rem; }} .original-link {{ display:inline-block; margin:.35rem 0 0; }} }}
  </style>
</head>
<body>
<header class="masthead"><div class="masthead-inner"><p class="kicker">Hermione Hermes · LinkedIn research filing</p><h1>Signals worth carrying forward.</h1><p>A living, newest-first scroll of articles shared through <strong>@al_hermoine_linkedin_bot</strong>, with the original post, archived image, research assessment, relevance, and caveats kept together.</p><div class="stats"><span id="article-count">{count} filed articles</span><span>Newest filing first</span><span>Public / guest-visible source archives</span></div></div></header>
<main>
  <aside class="note">This is a research filing surface, not an endorsement. It publishes selected public post text, locally archived post media, and Hermione’s research notes. It excludes raw HTML, authenticated-page captures, browser/session data, and comments.</aside>
  <section id="entries" aria-live="polite"></section>
  <div class="load-area"><p id="progress">Loading filings…</p><button id="load-more" type="button" hidden>Show 20 more</button><div id="scroll-sentinel" aria-hidden="true"></div></div>
  <noscript>This archive needs JavaScript enabled to load its paginated public filings.</noscript>
  <footer>Built from the sanitized LinkedIn intake archive. New filings are merged with the existing public index, so a partial intake source cannot remove older filings.</footer>
</main>
<script>
(() => {{
  const PAGE_SIZE = 20;
  const entries = document.getElementById("entries");
  const progress = document.getElementById("progress");
  const more = document.getElementById("load-more");
  let posts = [];
  let shown = 0;
  const element = (name, className, text) => {{ const node = document.createElement(name); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }};
  const date = value => {{ if (!value) return "Undated"; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleDateString("en-GB", {{ day:"2-digit", month:"short", year:"numeric" }}); }};
  const url = value => {{ try {{ const parsed = new URL(value); return /^https?:$/.test(parsed.protocol) ? parsed.href : ""; }} catch (_) {{ return ""; }} }};
  function card(post) {{
    const article = element("article", "entry"); article.id = "post-" + post.activity_id;
    article.append(element("div", "entry-number", String(post.number)));
    const body = element("div", "entry-body");
    body.append(element("p", "eyebrow", `Filed ${{date(post.filed_at)}} · Published ${{date(post.published_at)}}`));
    body.append(element("h2", "", post.title));
    const byline = element("p", "byline", "By "); const authorURL = url(post.author_url);
    if (authorURL) {{ const author = element("a", "", post.author); author.href = authorURL; author.rel = "noopener noreferrer"; byline.append(author); }} else byline.append(post.author);
    const originalURL = url(post.canonical_url); if (originalURL) {{ const original = element("a", "original-link", "Open original LinkedIn post ↗"); original.href = originalURL; original.rel = "noopener noreferrer"; byline.append(" ", original); }}
    body.append(byline, element("p", "headline", post.headline));
    if (post.images && post.images.length) {{ const media = element("div", "media"); post.images.forEach(src => {{ const image = document.createElement("img"); image.loading = "lazy"; image.src = src; image.alt = "Archived LinkedIn media for " + post.title; media.append(image); }}); body.append(media); }}
    const research = element("section", "research"); research.innerHTML = post.summary_html || "<p>Research summary is pending for this archive.</p>"; body.append(research);
    const details = document.createElement("details"); details.append(element("summary", "", "Archived LinkedIn post text"), element("div", "post-text", post.post_text)); body.append(details);
    article.append(body); return article;
  }}
  function renderNext() {{ const next = posts.slice(shown, shown + PAGE_SIZE); next.forEach(post => entries.append(card(post))); shown += next.length; progress.textContent = `Showing ${{shown}} of ${{posts.length}} filed articles`; more.hidden = shown >= posts.length; }}
  more.addEventListener("click", renderNext);
  const observer = new IntersectionObserver(items => {{ if (items.some(item => item.isIntersecting) && shown < posts.length) renderNext(); }}, {{ rootMargin:"500px" }});
  observer.observe(document.getElementById("scroll-sentinel"));
  fetch("posts.json").then(response => {{ if (!response.ok) throw new Error("archive index unavailable"); return response.json(); }}).then(data => {{ posts = Array.isArray(data.posts) ? data.posts : []; document.getElementById("article-count").textContent = `${{posts.length}} filed articles`; renderNext(); }}).catch(() => {{ progress.textContent = "The public filing index could not be loaded. Please refresh."; }});
}})();
</script>
</body>
</html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    if not args.source.is_dir():
        raise SystemExit(f"Archive source not found: {args.source}")
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = merge_records(collect_posts(args.source), load_published_records())
    if not records:
        raise SystemExit("No publishable archive records found")
    payload = public_payload(records)
    OUTPUT.write_text(build_page(int(payload["count"])), encoding="utf-8")
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps({"count": payload["count"], "activity_ids": [post["activity_id"] for post in payload["posts"]]}, indent=2) + "\n", encoding="utf-8")
    print(f"Built {OUTPUT} with {payload['count']} articles and {sum(len(post['images']) for post in payload['posts'])} images")


if __name__ == "__main__":
    main()
