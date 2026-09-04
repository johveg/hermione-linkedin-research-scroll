import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_site.py"
spec = importlib.util.spec_from_file_location("build_site", SCRIPT)
build_site = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_site)


def record(activity_id: str, filed_at: str) -> dict[str, object]:
    return {
        "activity_id": activity_id,
        "title": f"Title {activity_id}",
        "headline": "A headline",
        "author": "Author",
        "author_url": "",
        "canonical_url": "https://www.linkedin.com/posts/example",
        "published_at": filed_at,
        "filed_at": filed_at,
        "post_text": "Public post text",
        "summary": "## Post summary\n\nPublic assessment.",
        "images": [],
    }


def test_merge_records_keeps_previously_published_posts_when_source_is_partial():
    published = [
        record("old", "2026-07-01T10:00:00Z"),
        record("current", "2026-07-02T10:00:00Z"),
    ]
    source = [
        record("current", "2026-08-01T10:00:00Z"),
        record("new", "2026-08-02T10:00:00Z"),
    ]

    merged = build_site.merge_records(source, published)

    assert [item["activity_id"] for item in merged] == ["new", "current", "old"]
    assert next(item for item in merged if item["activity_id"] == "current")["filed_at"] == "2026-08-01T10:00:00Z"


def test_posts_payload_is_safe_render_data_not_raw_html():
    payload = build_site.public_payload([record("one", "2026-08-02T10:00:00Z")])

    assert payload["count"] == 1
    item = payload["posts"][0]
    assert item["activity_id"] == "one"
    assert "summary_html" in item
    assert "summary" not in item
    assert "<script" not in json.dumps(payload).lower()


def test_page_uses_first_page_of_twenty_with_progressive_load_button():
    page = build_site.build_page(42)

    assert 'id="entries"' in page
    assert 'id="load-more"' in page
    assert "PAGE_SIZE = 20" in page
    assert 'fetch("posts.json")' in page
    assert "Showing 20 of 42 filed articles" not in page  # populated by browser runtime


def test_publisher_stages_the_durable_public_index():
    publisher_script = Path(__file__).resolve().parents[1] / "scripts" / "publish_from_linkedin_intake.py"
    publisher_spec = importlib.util.spec_from_file_location("publisher", publisher_script)
    publisher = importlib.util.module_from_spec(publisher_spec)
    assert publisher_spec.loader is not None
    publisher_spec.loader.exec_module(publisher)

    assert "posts.json" in publisher.PUBLIC_PATHS
