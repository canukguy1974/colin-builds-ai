from __future__ import annotations

import csv
import html
import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
ENV_PATH = ROOT / ".env"
DB_PATH = ROOT / "data" / "radar.db"
REPORT_DIR = ROOT / "reports"


@dataclass
class Item:
    source: str
    source_id: str
    title: str
    url: str
    description: str = ""
    author: str = ""
    published_at: str | None = None
    metrics: dict[str, float | int] = field(default_factory=dict)
    previous_metrics: dict[str, float | int] = field(default_factory=dict)
    score: int = 0
    score_parts: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


def load_env() -> None:
    if not ENV_PATH.exists():
        return
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def get_json(url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
    merged = {"User-Agent": "colin-builds-ai-trend-radar/0.1", "Accept": "application/json"}
    if headers:
        merged.update(headers)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(url, params=params, headers=merged, timeout=25)
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Request failed for {url}: {last_error}")


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def fetch_github(config: dict[str, Any]) -> list[Item]:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    lookback = int(config["radar"]["lookback_days"])
    created_after = (datetime.now(timezone.utc) - timedelta(days=lookback)).date().isoformat()
    source = config["sources"]["github"]
    collected: dict[str, Item] = {}

    for query in source["queries"]:
        full_query = f"{query} created:>={created_after} stars:>={source['minimum_stars']}"
        payload = get_json(
            "https://api.github.com/search/repositories",
            params={"q": full_query, "sort": "stars", "order": "desc", "per_page": source["max_results_per_query"]},
            headers=headers,
        )
        for repo in payload.get("items", []):
            item = Item(
                source="github",
                source_id=str(repo["id"]),
                title=repo["full_name"],
                url=repo["html_url"],
                description=repo.get("description") or "",
                author=repo.get("owner", {}).get("login", ""),
                published_at=repo.get("created_at"),
                metrics={
                    "stars": repo.get("stargazers_count", 0),
                    "forks": repo.get("forks_count", 0),
                    "issues": repo.get("open_issues_count", 0),
                },
            )
            collected[item.key] = item
    return list(collected.values())


def fetch_huggingface(config: dict[str, Any]) -> list[Item]:
    source = config["sources"]["huggingface"]
    token = os.getenv("HF_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    items: list[Item] = []

    if source.get("models", True):
        payload = get_json(
            "https://huggingface.co/api/models",
            params={"sort": "trendingScore", "direction": -1, "limit": source["max_results_each"], "full": "true"},
            headers=headers,
        )
        for model in payload:
            model_id = model.get("id") or model.get("modelId")
            if not model_id:
                continue
            items.append(Item(
                source="huggingface-model",
                source_id=model_id,
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                description=" ".join(model.get("tags") or [])[:350],
                author=model_id.split("/", 1)[0] if "/" in model_id else "",
                published_at=model.get("createdAt") or model.get("lastModified"),
                metrics={
                    "likes": model.get("likes", 0),
                    "downloads": model.get("downloads", 0),
                    "trending": model.get("trendingScore", 0) or 0,
                },
            ))

    if source.get("spaces", True):
        payload = get_json(
            "https://huggingface.co/api/spaces",
            params={"sort": "trendingScore", "direction": -1, "limit": source["max_results_each"], "full": "true"},
            headers=headers,
        )
        for space in payload:
            space_id = space.get("id")
            if not space_id:
                continue
            items.append(Item(
                source="huggingface-space",
                source_id=space_id,
                title=space_id,
                url=f"https://huggingface.co/spaces/{space_id}",
                description=f"Interactive demo built with {space.get('sdk') or 'an unknown SDK'}.",
                author=space_id.split("/", 1)[0] if "/" in space_id else "",
                published_at=space.get("createdAt") or space.get("lastModified"),
                metrics={
                    "likes": space.get("likes", 0),
                    "trending": space.get("trendingScore", 0) or 0,
                },
            ))
    return items


def fetch_hackernews(config: dict[str, Any]) -> list[Item]:
    source = config["sources"]["hackernews"]
    keywords = [word.lower() for word in config["radar"]["keywords"]]
    collected: dict[int, Item] = {}

    for feed in source["feeds"]:
        ids = get_json(f"https://hacker-news.firebaseio.com/v0/{feed}.json")[: source["inspect_per_feed"]]
        for story_id in ids:
            story = get_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
            if not story or story.get("type") != "story":
                continue
            title = story.get("title", "")
            url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
            searchable = f"{title} {url}".lower()
            if not any(keyword in searchable for keyword in keywords):
                continue
            collected[story_id] = Item(
                source="hackernews",
                source_id=str(story_id),
                title=title,
                url=url,
                author=story.get("by", ""),
                published_at=datetime.fromtimestamp(story.get("time", 0), tz=timezone.utc).isoformat(),
                metrics={"points": story.get("score", 0), "comments": story.get("descendants", 0)},
            )
            if len(collected) >= source["max_results"]:
                break
    return list(collected.values())


def open_store() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS snapshots (
            item_key TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            metrics_json TEXT NOT NULL,
            PRIMARY KEY (item_key, captured_at)
        )
    """)
    return connection


def load_previous(connection: sqlite3.Connection, item: Item) -> dict[str, float | int]:
    row = connection.execute(
        "SELECT metrics_json FROM snapshots WHERE item_key = ? ORDER BY captured_at DESC LIMIT 1",
        (item.key,),
    ).fetchone()
    return json.loads(row[0]) if row else {}


def save_snapshot(connection: sqlite3.Connection, items: list[Item]) -> None:
    captured_at = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        "INSERT OR REPLACE INTO snapshots(item_key, captured_at, metrics_json) VALUES (?, ?, ?)",
        [(item.key, captured_at, json.dumps(item.metrics, sort_keys=True)) for item in items],
    )
    connection.commit()


def clamp(value: int) -> int:
    return max(1, min(5, value))


def score_item(item: Item) -> None:
    text = f"{item.title} {item.description}".lower()
    published = parse_date(item.published_at)
    age = max(0.0, (datetime.now(timezone.utc) - published).total_seconds() / 86400) if published else None

    delta = 0.0
    for metric in ("stars", "likes", "downloads", "points", "comments"):
        current = float(item.metrics.get(metric, 0) or 0)
        previous = float(item.previous_metrics.get(metric, current) or current)
        delta += max(0, current - previous)

    if delta >= 500:
        momentum = 5
    elif delta >= 100:
        momentum = 4
    elif delta >= 20:
        momentum = 3
    elif age is not None and age <= 3:
        momentum = 3
    elif age is not None and age <= 14:
        momentum = 2
    else:
        momentum = 1

    useful_words = ["agent", "automation", "workflow", "developer", "video", "voice", "browser", "search", "memory", "rag", "coding"]
    visual_words = ["demo", "video", "image", "voice", "browser", "ui", "app", "space", "multimodal"]
    business_words = ["sales", "lead", "customer", "business", "workflow", "automation", "content", "marketing", "support"]

    usefulness = clamp(1 + sum(word in text for word in useful_words) // 2)
    demonstration = clamp(1 + sum(word in text for word in visual_words))
    accessibility = 4 if item.source in {"github", "huggingface-space"} else 3
    originality = 4 if age is not None and age <= 7 else 3
    business = clamp(1 + sum(word in text for word in business_words))

    item.score_parts = {
        "momentum": momentum,
        "usefulness": usefulness,
        "demonstration": demonstration,
        "accessibility": accessibility,
        "originality": originality,
        "business": business,
    }
    item.score = sum(item.score_parts.values())
    item.reasons = [
        f"Momentum {momentum}/5" + (f" with +{int(delta)} measured growth" if delta else " using freshness and current activity"),
        f"Useful problem signals: {usefulness}/5",
        f"Visual demo potential: {demonstration}/5",
        f"Reproducibility: {accessibility}/5",
        f"Original-angle opportunity: {originality}/5",
        f"Business/content potential: {business}/5",
    ]


def write_reports(items: list[Item], errors: list[str]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    serializable = [asdict(item) for item in items]
    (REPORT_DIR / "latest.json").write_text(json.dumps({"items": serializable, "errors": errors}, indent=2), encoding="utf-8")

    with (REPORT_DIR / "latest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "score", "source", "title", "url", "description"])
        writer.writeheader()
        for rank, item in enumerate(items, 1):
            writer.writerow({"rank": rank, "score": item.score, "source": item.source, "title": item.title, "url": item.url, "description": item.description})

    cards = []
    for rank, item in enumerate(items, 1):
        metrics = " · ".join(f"{html.escape(str(k))}: {html.escape(str(v))}" for k, v in item.metrics.items())
        reasons = "".join(f"<li>{html.escape(reason)}</li>" for reason in item.reasons)
        cards.append(f"""
        <article class="card" data-source="{html.escape(item.source)}" data-text="{html.escape((item.title + ' ' + item.description).lower())}">
          <div class="top"><span class="rank">#{rank}</span><span class="source">{html.escape(item.source)}</span><span class="score">{item.score}/30</span></div>
          <h2><a href="{html.escape(item.url)}" target="_blank" rel="noreferrer">{html.escape(item.title)}</a></h2>
          <p>{html.escape(item.description or 'No description supplied.')}</p>
          <div class="metrics">{metrics}</div>
          <ul>{reasons}</ul>
        </article>""")

    warning_html = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Trend Radar</title><style>
:root{{color-scheme:dark;--bg:#07100d;--panel:#101b17;--border:#254237;--text:#effaf5;--muted:#9ab2a8;--accent:#3ce7a1}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top,#153a2d,var(--bg) 38%);font-family:Inter,system-ui,sans-serif;color:var(--text)}}
header,main,.controls{{max-width:1180px;margin:auto;padding-left:22px;padding-right:22px}}header{{padding-top:56px;padding-bottom:24px}}h1{{font-size:clamp(2.5rem,7vw,5.5rem);letter-spacing:-.06em;margin:.2em 0}}header p,.metrics{{color:var(--muted)}}
.controls{{display:flex;gap:12px;padding-bottom:22px;position:sticky;top:0;backdrop-filter:blur(16px);z-index:2}}input,select{{background:#0a1411dd;color:var(--text);border:1px solid var(--border);border-radius:12px;padding:12px}}input{{flex:1}}
main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:18px;padding-bottom:70px}}.card{{background:linear-gradient(145deg,var(--panel),#14241e);border:1px solid var(--border);border-radius:20px;padding:20px;box-shadow:0 18px 50px #0007}}.top{{display:flex;gap:10px;align-items:center}}.score{{margin-left:auto;color:var(--accent);font-weight:800}}.source,.rank{{color:var(--muted)}}a{{color:var(--text);text-decoration:none}}a:hover{{color:var(--accent)}}li{{margin:.45rem 0;color:#c9dbd3}}.warnings{{max-width:1180px;margin:0 auto 20px;padding:0 22px;color:#ffd58a}}
</style></head><body>
<header><div style="color:var(--accent);font-weight:800;letter-spacing:.16em;text-transform:uppercase">Colin Builds AI</div><h1>AI Trend Radar</h1><p>{len(items)} candidates ranked by momentum, usefulness, demo potential, accessibility, originality, and business value.</p></header>
<div class="controls"><input id="search" placeholder="Filter projects…"><select id="source"><option value="">All sources</option><option>github</option><option>huggingface-model</option><option>huggingface-space</option><option>hackernews</option></select></div>
<div class="warnings"><ul>{warning_html}</ul></div><main>{''.join(cards)}</main>
<script>const q=document.querySelector('#search'),s=document.querySelector('#source');function f(){{document.querySelectorAll('.card').forEach(c=>{{c.hidden=!(c.dataset.text.includes(q.value.toLowerCase())&&(!s.value||c.dataset.source===s.value))}})}}q.oninput=f;s.onchange=f;</script>
</body></html>"""
    (REPORT_DIR / "latest.html").write_text(document, encoding="utf-8")


def main() -> int:
    load_env()
    config = load_config()
    all_items: list[Item] = []
    errors: list[str] = []

    for fetcher in (fetch_github, fetch_huggingface, fetch_hackernews):
        try:
            all_items.extend(fetcher(config))
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")

    unique = {item.key: item for item in all_items}
    items = list(unique.values())

    with open_store() as connection:
        for item in items:
            item.previous_metrics = load_previous(connection, item)
            score_item(item)
        save_snapshot(connection, items)

    minimum = int(config["radar"]["minimum_score"])
    top_n = int(config["radar"]["top_n"])
    ranked = sorted((item for item in items if item.score >= minimum), key=lambda item: item.score, reverse=True)[:top_n]
    write_reports(ranked, errors)

    print(f"Found {len(ranked)} ranked candidates.")
    print(f"Dashboard: {REPORT_DIR / 'latest.html'}")
    if errors:
        print("Warnings:")
        for error in errors:
            print(f"- {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
