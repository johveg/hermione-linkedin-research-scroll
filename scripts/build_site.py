#!/usr/bin/env python3
"""Build the public, single-page LinkedIn research scroll from sanitized archives.

Only selected public artifacts are copied: metadata, post text, intake research,
and locally archived post media. Raw HTML, browser/session artifacts, comments,
and authenticated-page captures are intentionally excluded.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE = Path("/home/hermoine/agent-research-linkedin-source/data/posts")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "index.html"
ASSETS = ROOT / "assets" / "posts"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def clean_text(value: object) -> str:
    return "\n".join(line.rstrip() for line in str(value or "").replace("\x00", "").splitlines()).strip()


def title_from_summary(summary: str, fallback: str) -> str:
    for line in summary.splitlines():
        if line.startswith("# "):
            return clean_text(line[2:])
    return fallback


def format_date(value: str) -> str:
    if not value:
        return "Undated"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return value


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
            flush_paragraph(); close_list()
            if len(heading.group(1)) > 1:
                out.append("<h3>" + inline(heading.group(2)) + "</h3>")
            continue
        if line.startswith("> "):
            flush_paragraph(); close_list()
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
    flush_paragraph(); close_list()
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
        post = metadata.get("post") or {}
        author = metadata.get("author") or {}
        summary_path = post_dir / "intake-summary.md"
        raw_summary = summary_path.read_text(encoding="utf-8", errors="replace") if summary_path.exists() else ""
        summary = public_summary(raw_summary)
        headline = clean_text(post.get("headline")) or clean_text(post_path.read_text(encoding="utf-8", errors="replace").splitlines()[0] if post_path.read_text(encoding="utf-8", errors="replace") else "Untitled archive")
        title = title_from_summary(raw_summary, headline)
        published_at = clean_text(post.get("published_at"))
        filed_at = clean_text(metadata.get("fetched_at")) or published_at
        records.append({
            "activity_id": activity_id,
            "title": title,
            "headline": headline,
            "author": clean_text(author.get("name")) or "LinkedIn author",
            "author_url": clean_text(author.get("profile_url")),
            "canonical_url": clean_text(metadata.get("canonical_url")) or clean_text(metadata.get("input_url")),
            "published_at": published_at,
            "filed_at": filed_at,
            "post_text": clean_text(post_path.read_text(encoding="utf-8", errors="replace")),
            "summary": summary,
            "images": copy_media(post_dir, activity_id),
        })
    return sorted(records, key=lambda r: (str(r["filed_at"]), str(r["published_at"])), reverse=True)


def render_card(record: dict[str, object], index: int) -> str:
    title = html.escape(str(record["title"]))
    author = html.escape(str(record["author"]))
    author_url = html.escape(str(record["author_url"]), quote=True)
    canonical = html.escape(str(record["canonical_url"]), quote=True)
    post_text = html.escape(str(record["post_text"]))
    summary = markdown_to_html(str(record["summary"])) if record["summary"] else "<p>Research summary is pending for this archive.</p>"
    images = record["images"]
    media = "".join(f'<img loading="lazy" src="{html.escape(str(src), quote=True)}" alt="Archived LinkedIn media for {title}">' for src in images)
    author_markup = f'<a href="{author_url}" rel="noopener noreferrer">{author}</a>' if author_url else author
    original_link = f'<a class="original-link" href="{canonical}" rel="noopener noreferrer">Open original LinkedIn post ↗</a>' if canonical else ""
    return f'''<article class="entry" id="post-{html.escape(str(record["activity_id"]), quote=True)}">
  <div class="entry-number">{index:02d}</div>
  <div class="entry-body">
    <p class="eyebrow">Filed {format_date(str(record["filed_at"]))} · Published {format_date(str(record["published_at"]))}</p>
    <h2>{title}</h2>
    <p class="byline">By {author_markup} {original_link}</p>
    <p class="headline">{html.escape(str(record["headline"]))}</p>
    <div class="media">{media}</div>
    <section class="research">{summary}</section>
    <details><summary>Archived LinkedIn post text</summary><div class="post-text">{post_text}</div></details>
  </div>
</article>'''


def build_page(records: list[dict[str, object]]) -> str:
    cards = "\n".join(render_card(record, i + 1) for i, record in enumerate(records))
    latest_filing = max((str(record["filed_at"]) for record in records), default="")
    latest_label = format_date(latest_filing)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="A chronological, research-backed scroll of LinkedIn articles filed by Hermione Hermes.">
  <title>Hermione LinkedIn Research Scroll</title>
  <style>
    :root {{ --ink:#172033; --muted:#5d677c; --paper:#fffdf8; --wash:#edf4f2; --line:#d8dfdf; --accent:#126b64; --accent-pale:#d8eee9; --serif: Georgia, 'Times New Roman', serif; --sans: Inter, ui-sans-serif, system-ui, sans-serif; }}
    * {{ box-sizing:border-box; }} html {{ scroll-behavior:smooth; }} body {{ margin:0; color:var(--ink); background:var(--paper); font-family:var(--sans); line-height:1.62; }}
    a {{ color:var(--accent); text-decoration-thickness:1px; text-underline-offset:3px; }}
    .masthead {{ padding:clamp(3rem,8vw,7rem) max(1.25rem,calc((100vw - 1060px)/2)); background:linear-gradient(130deg,#123e46,#1e6b64 70%,#5ba99d); color:white; }}
    .masthead-inner {{ max-width:900px; }} .kicker,.eyebrow {{ margin:0; text-transform:uppercase; letter-spacing:.12em; font-size:.73rem; font-weight:750; }} .masthead h1 {{ max-width:750px; font-family:var(--serif); font-size:clamp(2.5rem,6vw,5.4rem); line-height:.98; font-weight:500; margin:.7rem 0 1.2rem; }} .masthead p:not(.kicker) {{ max-width:690px; margin:0; font-size:1.05rem; color:#e1f5ef; }}
    .stats {{ display:flex; flex-wrap:wrap; gap:.75rem; margin-top:1.8rem; }} .stats span {{ padding:.45rem .7rem; border:1px solid #91c9bf; border-radius:999px; font-size:.84rem; }}
    main {{ max-width:1060px; margin:auto; padding:clamp(2rem,5vw,5rem) 1.25rem 7rem; }} .note {{ max-width:780px; padding:1rem 1.2rem; margin:0 0 3rem; background:var(--wash); border-left:4px solid var(--accent); color:#354b50; font-size:.93rem; }}
    .entry {{ display:grid; grid-template-columns:76px minmax(0,1fr); gap:1.2rem; border-top:1px solid var(--line); padding:3.2rem 0; }} .entry-number {{ color:var(--accent); font-family:var(--serif); font-size:1.85rem; line-height:1; padding-top:.45rem; }} .entry-body {{ max-width:810px; }} .eyebrow {{ color:var(--muted); }} h2 {{ font-family:var(--serif); font-size:clamp(1.75rem,3.6vw,3rem); line-height:1.08; font-weight:500; margin:.45rem 0 .8rem; }} .byline {{ margin:0 0 1.2rem; color:var(--muted); font-size:.92rem; }} .original-link {{ margin-left:.55rem; white-space:nowrap; }} .headline {{ font-family:var(--serif); font-size:1.2rem; line-height:1.45; margin:0 0 1.4rem; }}
    .media {{ display:grid; gap:1rem; margin:1.3rem 0 2rem; }} .media img {{ max-width:100%; max-height:650px; border:1px solid var(--line); border-radius:5px; background:#f5f5f5; object-fit:contain; }} .research {{ font-size:1rem; }} .research h3 {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.1em; color:var(--accent); margin:2rem 0 .55rem; }} .research p {{ margin:.7rem 0; }} .research ul {{ padding-left:1.25rem; }} blockquote {{ margin:1.1rem 0; padding:.8rem 1rem; border-left:3px solid var(--accent); background:#f5faf8; font-family:var(--serif); font-size:1.08rem; }} code {{ font-size:.9em; background:#eef1f1; padding:.1em .25em; }} details {{ margin-top:1.7rem; border-top:1px solid var(--line); padding-top:.7rem; }} summary {{ cursor:pointer; color:var(--accent); font-weight:700; }} .post-text {{ white-space:pre-wrap; margin-top:.8rem; color:#445; font-size:.92rem; }} footer {{ border-top:1px solid var(--line); padding:2rem 0 0; color:var(--muted); font-size:.88rem; }}
    @media (max-width:620px) {{ .entry {{ grid-template-columns:1fr; gap:.5rem; }} .entry-number {{ font-size:1.2rem; }} .original-link {{ display:inline-block; margin:.35rem 0 0; }} }}
  </style>
</head>
<body>
<header class="masthead"><div class="masthead-inner"><p class="kicker">Hermione Hermes · LinkedIn research filing</p><h1>Signals worth carrying forward.</h1><p>A living, newest-first scroll of articles shared through <strong>@al_hermoine_linkedin_bot</strong>, with the original post, archived image, research assessment, relevance, and caveats kept together.</p><div class="stats"><span>{len(records)} filed articles</span><span>Newest filing first</span><span>Public / guest-visible source archives</span></div></div></header>
<main>
  <aside class="note">This is a research filing surface, not an endorsement. It publishes selected public post text, locally archived post media, and Hermione’s research notes. It excludes raw HTML, authenticated-page captures, browser/session data, and comments.</aside>
  {cards}
  <footer>Built from the sanitized LinkedIn intake archive. Latest filing: {latest_label}. New filings are added by rebuilding this page and publishing the resulting static site.</footer>
</main>
</body>
</html>'''


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    if not args.source.is_dir():
        raise SystemExit(f"Archive source not found: {args.source}")
    ASSETS.mkdir(parents=True, exist_ok=True)
    records = collect_posts(args.source)
    if not records:
        raise SystemExit("No publishable archive records found")
    OUTPUT.write_text(build_page(records), encoding="utf-8")
    (ROOT / "manifest.json").write_text(json.dumps({"count": len(records), "activity_ids": [r["activity_id"] for r in records]}, indent=2) + "\n", encoding="utf-8")
    print(f"Built {OUTPUT} with {len(records)} articles and {sum(len(r['images']) for r in records)} images")


if __name__ == "__main__":
    main()
