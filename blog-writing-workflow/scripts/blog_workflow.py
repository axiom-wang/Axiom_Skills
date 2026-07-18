#!/usr/bin/env python3
"""Config-driven research-to-blog workbench for blog-writing-workflow."""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import email.utils
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


UTC = dt.timezone.utc
CONFIG_RELATIVE_PATH = Path("references/topic-sources.json")
WRITING_PROFILES_RELATIVE_PATH = Path("references/writing-profiles.json")
CLAUDE_BLOG_RELATIVE_PATH = Path("claude-blog")

ARTICLE_TYPES = (
    "how-to-guide",
    "listicle",
    "case-study",
    "comparison",
    "pillar-page",
    "product-review",
    "thought-leadership",
    "roundup",
    "tutorial",
    "news-analysis",
    "data-research",
    "faq-knowledge",
)

AUTO_KEYWORDS = {
    "ai",
    "agent",
    "agents",
    "automation",
    "browser",
    "claude",
    "code",
    "coding",
    "developer",
    "gpt",
    "llm",
    "model",
    "open",
    "openai",
    "product",
    "research",
    "tool",
    "workflow",
    "智能体",
    "大模型",
    "产品",
    "技术",
    "趋势",
}

STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "also",
    "and",
    "are",
    "ask",
    "but",
    "can",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "its",
    "new",
    "not",
    "now",
    "our",
    "show",
    "that",
    "the",
    "their",
    "this",
    "use",
    "using",
    "was",
    "what",
    "when",
    "why",
    "with",
    "you",
    "your",
}


@dataclasses.dataclass
class EvidenceItem:
    source: str
    title: str
    url: str
    source_id: str = ""
    category: str = ""
    summary: str = ""
    published: str = ""
    score: float = 0.0
    labels: list[str] = dataclasses.field(default_factory=list)
    metrics: dict[str, Any] = dataclasses.field(default_factory=dict)
    raw: dict[str, Any] = dataclasses.field(default_factory=dict)
    status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class CategoryResolution:
    name: str
    confidence: float
    explicit: bool
    matched_keywords: list[str]


@dataclasses.dataclass
class ArticleTypeResolution:
    name: str
    reason: str
    confidence: float
    explicit: bool


@dataclasses.dataclass
class SourceRef:
    id: str
    name: str
    role: str
    kind: str
    description: str

    def to_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def skills_root() -> Path:
    return skill_dir().parent


def project_root() -> Path:
    return skill_dir().parents[2]


def claude_blog_root() -> Path:
    configured = os.environ.get("CLAUDE_BLOG_ROOT", "").strip()
    return Path(configured).expanduser() if configured else project_root() / CLAUDE_BLOG_RELATIVE_PATH


def humanizer_skill_path() -> Path:
    return skill_dir().parent / "humanizer-zh" / "SKILL.md"


def load_topic_config() -> dict[str, Any]:
    path = skill_dir() / CONFIG_RELATIVE_PATH
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config.get("categories"), list) or not isinstance(config.get("sources"), dict):
        raise ValueError("topic-sources.json must contain categories[] and sources{}")
    return config


def load_writing_profiles(topic_config: dict[str, Any] | None = None) -> dict[str, Any]:
    path = skill_dir() / WRITING_PROFILES_RELATIVE_PATH
    with path.open("r", encoding="utf-8") as handle:
        profiles = json.load(handle)
    categories = profiles.get("categories")
    article_types = profiles.get("article_types")
    global_rules = profiles.get("global_rules")
    if not isinstance(categories, dict) or not isinstance(article_types, dict) or not isinstance(global_rules, list):
        raise ValueError("writing-profiles.json must contain global_rules[], categories{}, and article_types{}")
    required_category_fields = {
        "voice",
        "evidence_requirements",
        "required_moves",
        "prohibited_moves",
        "action_style",
        "risk_disclosure",
        "validation_checks",
    }
    for name, profile in categories.items():
        missing = sorted(required_category_fields - set(profile))
        if missing:
            raise ValueError(f"Writing profile {name} is missing fields: {', '.join(missing)}")
    if topic_config is not None:
        configured_names = {str(category["name"]) for category in topic_config.get("categories", [])}
        profile_names = set(categories)
        if configured_names != profile_names:
            missing = sorted(configured_names - profile_names)
            extra = sorted(profile_names - configured_names)
            raise ValueError(f"Writing profile categories do not match topic categories; missing={missing}, extra={extra}")
    if set(article_types) != set(ARTICLE_TYPES):
        missing = sorted(set(ARTICLE_TYPES) - set(article_types))
        extra = sorted(set(article_types) - set(ARTICLE_TYPES))
        raise ValueError(f"Article type configuration mismatch; missing={missing}, extra={extra}")
    required_type_fields = {
        "purpose",
        "minimum_length",
        "recommended_max_length",
        "headline_patterns",
        "outline",
        "required_elements",
        "visuals",
        "faq_style",
        "conclusion_style",
    }
    for name, profile in article_types.items():
        missing = sorted(required_type_fields - set(profile))
        if missing:
            raise ValueError(f"Article type {name} is missing fields: {', '.join(missing)}")
        minimum_length = profile.get("minimum_length")
        recommended_max_length = profile.get("recommended_max_length")
        if (
            not isinstance(minimum_length, int)
            or isinstance(minimum_length, bool)
            or not isinstance(recommended_max_length, int)
            or isinstance(recommended_max_length, bool)
            or minimum_length <= 0
            or recommended_max_length <= 0
            or minimum_length > recommended_max_length
        ):
            raise ValueError(
                f"Article type {name} must define positive integer lengths with minimum_length <= recommended_max_length"
            )
    return profiles


def category_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {category["name"]: category for category in config.get("categories", [])}


def source_config(config: dict[str, Any], source_id: str) -> dict[str, Any]:
    sources = config.get("sources", {})
    if source_id not in sources:
        return {
            "name": source_id,
            "kind": "manual",
            "collector": "manual",
            "description": "Source is referenced by a category but is not registered.",
        }
    return sources[source_id]


def source_ref(config: dict[str, Any], source_id: str, role: str) -> SourceRef:
    source = source_config(config, source_id)
    return SourceRef(
        id=source_id,
        name=source.get("name", source_id),
        role=role,
        kind=source.get("kind", "manual"),
        description=source.get("description", ""),
    )


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


def parse_datetime(value: str | int | float | None) -> dt.datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return dt.datetime.fromtimestamp(value, tz=UTC)
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        pass
    try:
        fixed = raw.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(fixed)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except Exception:
        return None


def iso_date(value: str | int | float | None) -> str:
    parsed = parse_datetime(value)
    return parsed.astimezone(UTC).isoformat() if parsed else ""


def age_hours(iso_value: str) -> float:
    parsed = parse_datetime(iso_value)
    if not parsed:
        return 24 * 30
    return max(0.0, (dt.datetime.now(tz=UTC) - parsed.astimezone(UTC)).total_seconds() / 3600)


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9+\-.]*|[\u4e00-\u9fff]{2,}", text.lower())
    return [token for token in tokens if token not in STOPWORDS and len(token) > 1]


def unique_tokens(text: str) -> set[str]:
    return set(tokenize(text))


def slugify(text: str, fallback: str = "blog-run") -> str:
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", text.lower()).strip("-")
    return slug[:80] or fallback


def request_text(url: str, timeout: float, errors: list[dict[str, Any]], source: str | None = None) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "blog-writing-workflow/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except Exception as exc:
        errors.append({"source": source or url, "error": str(exc)})
        return None


def request_json(url: str, timeout: float, errors: list[dict[str, Any]], source: str | None = None) -> Any:
    text = request_text(url, timeout, errors, source=source)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append({"source": source or url, "error": f"invalid json: {exc}"})
        return None


def request_json_post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    errors: list[dict[str, Any]],
    source: str,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        errors.append({"source": source, "error": str(exc)})
        return None


def resolve_category(topic: str | None, explicit_category: str | None, config: dict[str, Any]) -> CategoryResolution:
    categories = category_map(config)
    if explicit_category:
        if explicit_category not in categories:
            valid = ", ".join(categories)
            raise ValueError(f"Unknown category: {explicit_category}. Valid categories: {valid}")
        return CategoryResolution(explicit_category, 1.0, True, [])

    if not topic:
        default_name = config.get("default_category") or next(iter(categories))
        return CategoryResolution(default_name, 0.0, False, [])

    text = topic.lower()
    topic_tokens = unique_tokens(topic)
    scored: list[tuple[float, str, list[str]]] = []
    for category in config.get("categories", []):
        matched: list[str] = []
        score = 0.0
        for keyword in category.get("keywords", []):
            keyword_text = str(keyword)
            keyword_lower = keyword_text.lower()
            keyword_tokens = unique_tokens(keyword_text)
            if keyword_lower in text:
                score += 2.0
                matched.append(keyword_text)
            elif keyword_tokens and topic_tokens & keyword_tokens:
                score += 1.0
                matched.append(keyword_text)
        for expansion in category.get("query_expansions", []):
            expansion_tokens = unique_tokens(str(expansion))
            overlap = len(topic_tokens & expansion_tokens)
            if overlap:
                score += min(1.5, overlap * 0.5)
        if score:
            scored.append((score, category["name"], matched))

    if not scored:
        default_name = config.get("default_category") or next(iter(categories))
        return CategoryResolution(default_name, 0.0, False, [])

    scored.sort(key=lambda row: row[0], reverse=True)
    best_score, best_name, matched = scored[0]
    confidence = min(0.95, 0.35 + best_score / 10)
    return CategoryResolution(best_name, round(confidence, 3), False, matched[:8])


def query_variants(topic: str | None, category_info: dict[str, Any]) -> list[str]:
    variants: list[str] = []
    if topic:
        variants.append(topic)
    variants.extend(str(item) for item in category_info.get("query_expansions", []))
    seen: set[str] = set()
    result: list[str] = []
    for variant in variants:
        normalized = variant.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def effective_query(topic: str | None, category_info: dict[str, Any]) -> str:
    variants = query_variants(topic, category_info)
    if variants:
        return variants[0] if topic else " ".join(variants[:2])
    return category_info.get("name", "")


def contains_cjk(text: str | None) -> bool:
    return bool(text and re.search(r"[\u4e00-\u9fff]", text))


def ascii_expansion(category_info: dict[str, Any]) -> str:
    for expansion in category_info.get("query_expansions", []):
        value = str(expansion).strip()
        if value and not contains_cjk(value):
            return value
    return ""


def source_query(source_id: str, topic: str | None, category_info: dict[str, Any], default_query: str) -> str:
    english_first_sources = {
        "ai-newsletters",
        "ai-products",
        "hackernews",
        "arxiv",
        "techmeme",
        "producthunt-rss",
        "github-trending",
        "producthunt-api",
    }
    if topic and source_id in english_first_sources and contains_cjk(topic):
        return ascii_expansion(category_info) or default_query
    return default_query


def list_categories(config: dict[str, Any]) -> None:
    sources = config.get("sources", {})
    payload = {
        "category_count": len(config.get("categories", [])),
        "categories": [],
    }
    for category in config.get("categories", []):
        entry = {
            "name": category["name"],
            "primary": [sources.get(source_id, {}).get("name", source_id) for source_id in category.get("primary", [])],
            "secondary": [sources.get(source_id, {}).get("name", source_id) for source_id in category.get("secondary", [])],
            "deep": [sources.get(source_id, {}).get("name", source_id) for source_id in category.get("deep", [])],
            "writing_helpers": [
                sources.get(source_id, {}).get("name", source_id) for source_id in category.get("writing_helpers", [])
            ],
        }
        payload["categories"].append(entry)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def check_source_availability(
    config: dict[str, Any],
    source_id: str,
    query: str,
) -> tuple[bool, str]:
    source = source_config(config, source_id)
    kind = source.get("kind", "manual")
    if kind in {"manual", "deep", "helper"}:
        return False, f"{kind} source; add during agent deep-dive rather than automatic collection"

    if source_id == "folo":
        if shutil.which("npx") is None:
            return False, "missing cli: npx"
        if os.environ.get("FOLO_TOKEN"):
            return True, ""
        try:
            proc = subprocess.run(
                ["npx", "--yes", "folocli@latest", "whoami"],
                capture_output=True,
                text=True,
                timeout=25,
                check=False,
            )
        except Exception as exc:
            return False, f"Folo auth check failed: {exc}"
        if proc.returncode == 0:
            return True, ""
        return False, "not logged in: run `npx --yes folocli@latest login` or set FOLO_TOKEN"

    missing_env = [name for name in source.get("requires_env", []) if not os.environ.get(name)]
    if missing_env:
        return False, f"missing env: {', '.join(missing_env)}"

    env_sets = source.get("requires_any_env_sets", [])
    if env_sets:
        has_any_set = any(all(os.environ.get(name) for name in env_set) for env_set in env_sets)
        if not has_any_set:
            formatted = " OR ".join("+".join(env_set) for env_set in env_sets)
            return False, f"missing env set: {formatted}"

    missing_cli = [name for name in source.get("requires_cli", []) if shutil.which(name) is None]
    if missing_cli:
        return False, f"missing cli: {', '.join(missing_cli)}"

    if source.get("requires_topic") and not query.strip():
        return False, "requires topic or category query"

    return True, ""


def resolve_sources(
    config: dict[str, Any],
    category_info: dict[str, Any],
    mode: str,
    query: str,
) -> tuple[list[SourceRef], list[dict[str, str]], list[SourceRef], list[SourceRef]]:
    enabled: list[SourceRef] = []
    skipped: list[dict[str, str]] = []
    recommended: list[SourceRef] = []
    helpers: list[SourceRef] = []
    seen: set[tuple[str, str]] = set()

    def add_recommended(source_id: str, role: str) -> None:
        key = (source_id, role)
        if key not in seen:
            seen.add(key)
            recommended.append(source_ref(config, source_id, role))

    for role in ("primary", "secondary"):
        for source_id in category_info.get(role, []):
            source = source_config(config, source_id)
            kind = source.get("kind", "manual")
            if kind in {"manual", "deep", "helper"}:
                add_recommended(source_id, role)
                continue
            available, reason = check_source_availability(config, source_id, query)
            ref = source_ref(config, source_id, role)
            if available:
                enabled.append(ref)
            else:
                skipped.append(
                    {
                        "id": source_id,
                        "name": ref.name,
                        "role": role,
                        "kind": ref.kind,
                        "reason": reason,
                    }
                )

    for source_id in category_info.get("deep", []):
        add_recommended(source_id, "deep")

    for source_id in category_info.get("writing_helpers", []):
        helpers.append(source_ref(config, source_id, "writing_helper"))

    if mode == "auto" and not enabled:
        fallback_ids = ["hackernews", "techmeme", "producthunt-rss", "github-trending", "ai-newsletters"]
        for source_id in fallback_ids:
            if any(ref.id == source_id for ref in enabled):
                continue
            available, reason = check_source_availability(config, source_id, query)
            ref = source_ref(config, source_id, "fallback")
            if available:
                enabled.append(ref)
            else:
                skipped.append(
                    {
                        "id": source_id,
                        "name": ref.name,
                        "role": "fallback",
                        "kind": ref.kind,
                        "reason": reason,
                    }
                )

    return enabled, skipped, recommended, helpers


def decorate_item(item: EvidenceItem, source_id: str, source_name: str, category: str, labels: list[str]) -> EvidenceItem:
    item.source_id = item.source_id or source_id
    item.source = item.source or source_name
    item.category = item.category or category
    merged_labels = list(dict.fromkeys([*labels, *item.labels]))
    item.labels = merged_labels
    return item


def collect_hn_algolia(
    topic: str,
    days: int,
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    cutoff = int(time.time()) - days * 86400
    params = urllib.parse.urlencode(
        {
            "query": topic,
            "tags": "story",
            "numericFilters": f"created_at_i>{cutoff}",
            "hitsPerPage": str(limit),
        }
    )
    data = request_json(f"https://hn.algolia.com/api/v1/search?{params}", timeout, errors, source="hackernews")
    items: list[EvidenceItem] = []
    for hit in (data or {}).get("hits", []):
        title = strip_html(hit.get("title") or hit.get("story_title"))
        if not title:
            continue
        object_id = hit.get("objectID")
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        items.append(
            EvidenceItem(
                source="Hacker News Search",
                source_id="hackernews",
                title=title,
                url=url,
                summary=strip_html(hit.get("story_text") or hit.get("comment_text")),
                published=iso_date(hit.get("created_at") or hit.get("created_at_i")),
                labels=["community", "trigger"],
                metrics={
                    "points": hit.get("points") or 0,
                    "comments": hit.get("num_comments") or 0,
                    "hn_id": object_id,
                    "discussion_url": f"https://news.ycombinator.com/item?id={object_id}" if object_id else "",
                },
                raw={"author": hit.get("author")},
            )
        )
    return items


def collect_hn_top(days: int, limit: int, timeout: float, errors: list[dict[str, Any]]) -> list[EvidenceItem]:
    ids = request_json("https://hacker-news.firebaseio.com/v0/topstories.json", timeout, errors, source="hackernews")
    if not isinstance(ids, list):
        return []
    cutoff = int(time.time()) - days * 86400
    items: list[EvidenceItem] = []
    for story_id in ids[:limit]:
        data = request_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout, errors, source="hackernews")
        if not isinstance(data, dict) or data.get("type") != "story":
            continue
        if data.get("time", 0) < cutoff:
            continue
        title = strip_html(data.get("title"))
        if not title:
            continue
        items.append(
            EvidenceItem(
                source="Hacker News Top",
                source_id="hackernews",
                title=title,
                url=data.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                summary=strip_html(data.get("text")),
                published=iso_date(data.get("time")),
                labels=["community", "trigger"],
                metrics={
                    "points": data.get("score") or 0,
                    "comments": data.get("descendants") or 0,
                    "hn_id": story_id,
                    "discussion_url": f"https://news.ycombinator.com/item?id={story_id}",
                },
                raw={"by": data.get("by")},
            )
        )
    return items


def collect_hn_show(
    topic: str | None,
    days: int,
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    cutoff = int(time.time()) - days * 86400
    params = {
        "tags": "show_hn",
        "numericFilters": f"created_at_i>{cutoff}",
        "hitsPerPage": str(limit),
    }
    if topic:
        params["query"] = topic
    data = request_json(
        f"https://hn.algolia.com/api/v1/search_by_date?{urllib.parse.urlencode(params)}",
        timeout,
        errors,
        source="hackernews-show",
    )
    items: list[EvidenceItem] = []
    for hit in (data or {}).get("hits", []):
        title = strip_html(hit.get("title") or hit.get("story_title"))
        object_id = hit.get("objectID")
        if not title:
            continue
        items.append(
            EvidenceItem(
                source="Show HN",
                source_id="ai-products",
                title=title,
                url=hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}",
                summary=strip_html(hit.get("story_text")),
                published=iso_date(hit.get("created_at") or hit.get("created_at_i")),
                labels=["community", "trigger", "product"],
                metrics={
                    "points": hit.get("points") or 0,
                    "comments": hit.get("num_comments") or 0,
                    "hn_id": object_id,
                },
            )
        )
    return items


def rss_child_text(node: ET.Element, names: list[str]) -> str:
    for name in names:
        found = node.find(name)
        if found is not None and found.text:
            return found.text
    for child in node:
        local = child.tag.split("}", 1)[-1]
        if local in names and child.text:
            return child.text
    return ""


def rss_link(node: ET.Element) -> str:
    direct = rss_child_text(node, ["link"])
    if direct:
        return direct.strip()
    for child in node:
        if child.tag.split("}", 1)[-1] == "link":
            href = child.attrib.get("href")
            if href:
                return href.strip()
    return ""


def collect_rss_feed(
    source_id: str,
    source_name: str,
    url: str,
    labels: list[str],
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
    topic: str | None = None,
    days: int | None = None,
) -> list[EvidenceItem]:
    text = request_text(url, timeout, errors, source=source_id)
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        errors.append({"source": source_id, "error": f"invalid rss: {exc}"})
        return []

    entries = root.findall(".//item")
    if not entries:
        entries = [node for node in root.iter() if node.tag.split("}", 1)[-1] == "entry"]

    topic_tokens = unique_tokens(topic or "")
    cutoff_dt = dt.datetime.now(tz=UTC) - dt.timedelta(days=days or 3650)
    items: list[EvidenceItem] = []
    for entry in entries[: limit * 4]:
        title = strip_html(rss_child_text(entry, ["title"]))
        summary = strip_html(rss_child_text(entry, ["description", "summary", "content"]))
        link = rss_link(entry)
        published = iso_date(rss_child_text(entry, ["pubDate", "published", "updated"]))
        parsed = parse_datetime(published)
        if days and parsed and parsed.astimezone(UTC) < cutoff_dt:
            continue
        combined_tokens = unique_tokens(f"{title} {summary}")
        if topic_tokens and not (topic_tokens & combined_tokens):
            continue
        if not title or not link:
            continue
        item_labels = list(labels)
        if any(token in combined_tokens for token in AUTO_KEYWORDS):
            item_labels.append("trigger")
        items.append(
            EvidenceItem(
                source=source_name,
                source_id=source_id,
                title=title,
                url=link,
                summary=summary[:700],
                published=published,
                labels=list(dict.fromkeys(item_labels)),
            )
        )
        if len(items) >= limit:
            break
    return items


def collect_arxiv(topic: str, limit: int, timeout: float, errors: list[dict[str, Any]]) -> list[EvidenceItem]:
    if not topic.strip():
        return []
    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{topic}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": str(limit),
        }
    )
    text = request_text(f"https://export.arxiv.org/api/query?{params}", timeout, errors, source="arxiv")
    if not text:
        return []
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        errors.append({"source": "arxiv", "error": f"invalid atom: {exc}"})
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items: list[EvidenceItem] = []
    for entry in root.findall("a:entry", ns):
        title_node = entry.find("a:title", ns)
        id_node = entry.find("a:id", ns)
        summary_node = entry.find("a:summary", ns)
        published_node = entry.find("a:published", ns)
        if title_node is None or id_node is None:
            continue
        title = strip_html(title_node.text)
        url = (id_node.text or "").strip()
        summary = strip_html(summary_node.text if summary_node is not None else "")
        if "withdrawn" in summary.lower():
            continue
        authors = []
        for author in entry.findall("a:author", ns):
            name = author.find("a:name", ns)
            if name is not None and name.text:
                authors.append(name.text)
        items.append(
            EvidenceItem(
                source="arXiv",
                source_id="arxiv",
                title=title,
                url=url,
                summary=summary[:900],
                published=iso_date(published_node.text if published_node is not None else ""),
                labels=["primary", "research"],
                metrics={"authors": authors[:6]},
            )
        )
    return items


def run_json_skill_script(
    script: Path,
    payload: dict[str, Any],
    source_id: str,
    timeout: float,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not script.exists():
        errors.append({"source": source_id, "error": f"script not found: {script}"})
        return None
    try:
        proc = subprocess.run(
            [sys.executable, str(script), json.dumps(payload, ensure_ascii=False)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception as exc:
        errors.append({"source": source_id, "error": str(exc)})
        return None
    if proc.returncode != 0:
        errors.append({"source": source_id, "error": proc.stderr.strip() or proc.stdout.strip()})
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        errors.append({"source": source_id, "error": f"invalid json: {exc}"})
        return None


def collect_zhihu_script(
    source_id: str,
    query: str,
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    script_map = {
        "global-search": skills_root() / "global-search" / "scripts" / "global-search.py",
        "zhihu-search": skills_root() / "zhihu-search" / "scripts" / "zhihu-search.py",
        "hot-list": skills_root() / "hot-list" / "scripts" / "hot-list.py",
    }
    payload: dict[str, Any]
    if source_id == "hot-list":
        payload = {"limit": min(limit, 30)}
    elif source_id == "global-search":
        payload = {"query": query, "count": min(limit, 20), "search_db": "all"}
    else:
        payload = {"query": query, "count": min(limit, 10)}
    data = run_json_skill_script(script_map[source_id], payload, source_id, timeout, errors)
    items: list[EvidenceItem] = []
    for row in (data or {}).get("items", []):
        title = strip_html(row.get("title"))
        url = row.get("url") or ""
        if not title or not url:
            continue
        metrics = {
            "author": row.get("author_name"),
            "thumbnail_url": row.get("thumbnail_url"),
            "vote_up_count": row.get("vote_up_count"),
            "comment_count": row.get("comment_count"),
        }
        labels = ["community", "trigger"] if source_id == "hot-list" else ["analysis", "community"]
        source_name = {
            "global-search": "Zhihu Global Search",
            "zhihu-search": "Zhihu Search",
            "hot-list": "Zhihu Hot List",
        }[source_id]
        items.append(
            EvidenceItem(
                source=source_name,
                source_id=source_id,
                title=title,
                url=url,
                summary=strip_html(row.get("summary")),
                published=iso_date(row.get("edit_time")),
                labels=labels,
                metrics={key: value for key, value in metrics.items() if value not in {None, ""}},
            )
        )
    return items


def collect_producthunt_api(
    category_info: dict[str, Any],
    days: int,
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    token = producthunt_access_token(timeout, errors)
    if not token:
        return []
    posted_after = (dt.datetime.now(tz=UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    query = """
    query GetPosts($first: Int, $featured: Boolean, $postedAfter: DateTime) {
      posts(first: $first, featured: $featured, postedAfter: $postedAfter) {
        edges {
          node {
            id
            name
            tagline
            slug
            votesCount
            commentsCount
            url
            website
            featuredAt
          }
        }
      }
    }
    """
    payload = {
        "query": query,
        "variables": {"first": min(limit, 50), "featured": True, "postedAfter": posted_after},
    }
    data = request_json_post(
        "https://api.producthunt.com/v2/api/graphql",
        payload,
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout,
        errors,
        "producthunt-api",
    )
    if not isinstance(data, dict) or data.get("errors"):
        if isinstance(data, dict) and data.get("errors"):
            errors.append({"source": "producthunt-api", "error": json.dumps(data["errors"], ensure_ascii=False)})
        return []
    items: list[EvidenceItem] = []
    for edge in data.get("data", {}).get("posts", {}).get("edges", []):
        post = edge.get("node") or {}
        title = strip_html(post.get("name"))
        url = post.get("website") or post.get("url") or ""
        if not title or not url:
            continue
        items.append(
            EvidenceItem(
                source="Product Hunt API",
                source_id="producthunt-api",
                title=title,
                url=url,
                summary=strip_html(post.get("tagline")),
                published=iso_date(post.get("featuredAt")),
                labels=["primary", "product", "trigger"],
                metrics={
                    "votes": post.get("votesCount") or 0,
                    "comments": post.get("commentsCount") or 0,
                    "producthunt_url": post.get("url"),
                    "slug": post.get("slug"),
                    "category": category_info.get("name"),
                },
            )
        )
    return items


def producthunt_access_token(timeout: float, errors: list[dict[str, Any]]) -> str:
    token = os.environ.get("PRODUCTHUNT_ACCESS_TOKEN", "").strip()
    if token:
        return token
    api_key = os.environ.get("PRODUCTHUNT_API_KEY", "").strip()
    api_secret = os.environ.get("PRODUCTHUNT_API_SECRET", "").strip()
    if not api_key or not api_secret:
        errors.append({"source": "producthunt-api", "error": "missing Product Hunt access token or API key/secret"})
        return ""
    data = request_json_post(
        "https://api.producthunt.com/v2/oauth/token",
        {
            "client_id": api_key,
            "client_secret": api_secret,
            "grant_type": "client_credentials",
        },
        {"Accept": "application/json", "Content-Type": "application/json"},
        timeout,
        errors,
        "producthunt-api-token",
    )
    if not isinstance(data, dict):
        return ""
    access_token = str(data.get("access_token") or "").strip()
    if not access_token:
        errors.append({"source": "producthunt-api", "error": "token exchange did not return access_token"})
    return access_token


def blockbeats_get(
    path: str,
    params: dict[str, str],
    timeout: float,
    errors: list[dict[str, Any]],
    source_id: str,
) -> Any:
    api_key = os.environ.get("BLOCKBEATS_API_KEY", "").strip()
    query = urllib.parse.urlencode(params)
    url = f"https://api-pro.theblockbeats.info{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(url, headers={"api-key": api_key, "User-Agent": "blog-writing-workflow/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        errors.append({"source": source_id, "error": str(exc)})
        return None


def extract_blockbeats_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    payload = data.get("data")
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("list", "items", "data", "rows", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return [payload] if payload else []


def normalize_blockbeats_rows(
    source_id: str,
    source_name: str,
    rows: list[dict[str, Any]],
    labels: list[str],
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for row in rows:
        title = strip_html(row.get("title") or row.get("name") or row.get("content") or row.get("abstract"))
        summary = strip_html(row.get("abstract") or row.get("summary") or row.get("content") or row.get("desc"))
        url = row.get("url") or row.get("link") or "https://www.theblockbeats.info/"
        published = iso_date(row.get("time") or row.get("created_at") or row.get("createdAt") or row.get("date"))
        if not title:
            title = source_name
        items.append(
            EvidenceItem(
                source=source_name,
                source_id=source_id,
                title=title,
                url=url,
                summary=summary[:900] or json.dumps(row, ensure_ascii=False)[:900],
                published=published,
                labels=labels,
                metrics={"time_cn": row.get("time_cn"), "type": row.get("type")},
                raw=row,
            )
        )
    return items


def collect_blockbeats_search(
    query: str,
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    if query.strip():
        data = blockbeats_get(
            "/v1/search",
            {"name": query, "size": str(min(limit, 100)), "lang": "en"},
            timeout,
            errors,
            "blockbeats-skill",
        )
    else:
        data = blockbeats_get(
            "/v1/newsflash/important",
            {"page": "1", "size": str(min(limit, 50)), "lang": "en"},
            timeout,
            errors,
            "blockbeats-skill",
        )
    return normalize_blockbeats_rows(
        "blockbeats-skill",
        "BlockBeats Search and News",
        extract_blockbeats_rows(data),
        ["analysis", "trigger", "market"],
    )


def collect_blockbeats_data_bundle(
    source_id: str,
    endpoints: list[tuple[str, dict[str, str], str]],
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    source_name = "BlockBeats Macro Data" if source_id == "blockbeats-macro" else "BlockBeats Market Data"
    labels = ["primary", "macro"] if source_id == "blockbeats-macro" else ["primary", "market"]
    for path, params, title in endpoints:
        data = blockbeats_get(path, params, timeout, errors, source_id)
        if data is None:
            continue
        payload = data.get("data") if isinstance(data, dict) else data
        items.append(
            EvidenceItem(
                source=source_name,
                source_id=source_id,
                title=title,
                url="https://www.theblockbeats.info/",
                summary=json.dumps(payload, ensure_ascii=False)[:1000],
                published=dt.datetime.now(tz=UTC).isoformat(),
                labels=labels,
                raw={"endpoint": path, "params": params, "response": payload},
            )
        )
    return items


def collect_folo_trending(
    category_info: dict[str, Any],
    limit: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    keyword = category_info.get("name", "")
    cmd = [
        "npx",
        "--yes",
        "folocli@latest",
        "search",
        "trending",
        "--range",
        "7d",
        "--limit",
        str(min(limit, 20)),
        "--language",
        "cmn",
        "--category",
        keyword,
        "--format",
        "json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as exc:
        errors.append({"source": "folo", "error": str(exc)})
        return []
    if proc.returncode != 0:
        errors.append({"source": "folo", "error": proc.stderr.strip() or proc.stdout.strip()})
        return []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        errors.append({"source": "folo", "error": f"invalid json: {exc}"})
        return []
    entries = data.get("data", data)
    if isinstance(entries, dict):
        entries = entries.get("entries") or entries.get("items") or entries.get("feeds") or []
    if not isinstance(entries, list):
        return []
    items: list[EvidenceItem] = []
    for row in entries[:limit]:
        if not isinstance(row, dict):
            continue
        title = strip_html(row.get("title") or row.get("name"))
        url = row.get("url") or row.get("siteUrl") or row.get("entryUrl") or ""
        if not title:
            continue
        items.append(
            EvidenceItem(
                source="Folo",
                source_id="folo",
                title=title,
                url=url,
                summary=strip_html(row.get("description") or row.get("summary") or row.get("content")),
                published=iso_date(row.get("publishedAt") or row.get("createdAt") or row.get("updatedAt")),
                labels=["analysis", "rss"],
                metrics={"feed_id": row.get("feedId"), "entry_id": row.get("id")},
                raw=row,
            )
        )
    return items


def run_collector(
    source: SourceRef,
    config: dict[str, Any],
    category_info: dict[str, Any],
    topic: str | None,
    query: str,
    mode: str,
    per_source_limit: int,
    days: int,
    timeout: float,
    errors: list[dict[str, Any]],
) -> list[EvidenceItem]:
    source_cfg = source_config(config, source.id)
    collector = source_cfg.get("collector")
    labels = list(source_cfg.get("labels", []))
    source_name = source_cfg.get("name", source.id)
    collector_query = source_query(source.id, topic, category_info, query)
    category_routed_auto = mode == "auto" and category_info.get("name") != "互联网与科技趋势"
    rss_topic = collector_query if (mode == "topic" or category_routed_auto) else None

    if collector == "hackernews":
        items = collect_hn_algolia(collector_query, days, per_source_limit, timeout, errors) if (topic or category_routed_auto) else collect_hn_top(days, per_source_limit, timeout, errors)
    elif collector == "arxiv":
        items = collect_arxiv(collector_query, per_source_limit, timeout, errors)
    elif collector == "rss":
        items = collect_rss_feed(source.id, source_name, source_cfg["url"], labels, per_source_limit, timeout, errors, topic=rss_topic, days=days)
    elif collector == "rss_bundle":
        items = []
        for feed in source_cfg.get("feeds", []):
            items.extend(
                collect_rss_feed(
                    source.id,
                    feed.get("name", source_name),
                    feed["url"],
                    labels,
                    max(2, per_source_limit // max(1, len(source_cfg.get("feeds", [])))),
                    timeout,
                    errors,
                    topic=rss_topic,
                    days=days,
                )
            )
    elif collector == "ai_products":
        items = []
        for feed in source_cfg.get("feeds", []):
            items.extend(
                collect_rss_feed(
                    source.id,
                    feed.get("name", source_name),
                    feed["url"],
                    labels,
                    max(2, per_source_limit // 2),
                    timeout,
                    errors,
                    topic=rss_topic,
                    days=days,
                )
            )
        items.extend(collect_hn_show(topic, days, max(3, per_source_limit // 2), timeout, errors))
    elif collector in {"zhihu_global", "zhihu_search", "zhihu_hot"}:
        items = collect_zhihu_script(source.id, collector_query, per_source_limit, timeout, errors)
    elif collector == "producthunt_api":
        items = collect_producthunt_api(category_info, days, per_source_limit, timeout, errors)
    elif collector == "blockbeats_search":
        items = collect_blockbeats_search(collector_query if (topic or category_routed_auto) else "", per_source_limit, timeout, errors)
    elif collector == "blockbeats_macro":
        items = collect_blockbeats_data_bundle(
            "blockbeats-macro",
            [
                ("/v1/data/m2_supply", {"type": "1Y"}, "Global M2 supply"),
                ("/v1/data/us10y", {"type": "1M"}, "US 10Y Treasury yield"),
                ("/v1/data/dxy", {"type": "1M"}, "DXY Dollar Index"),
                ("/v1/data/compliant_total", {}, "Compliant exchange total assets"),
            ],
            timeout,
            errors,
        )
    elif collector == "blockbeats_market":
        items = collect_blockbeats_data_bundle(
            "blockbeats-market",
            [
                ("/v1/data/bottom_top_indicator", {}, "Crypto market sentiment indicator"),
                ("/v1/data/btc_etf", {}, "BTC ETF net inflow"),
                ("/v1/data/stablecoin_marketcap", {}, "Stablecoin market cap"),
                ("/v1/data/daily_tx", {}, "Daily on-chain transaction volume"),
            ],
            timeout,
            errors,
        )
    elif collector == "folo_trending":
        items = collect_folo_trending(category_info, per_source_limit, timeout, errors)
    else:
        errors.append({"source": source.id, "error": f"collector not implemented: {collector}"})
        return []

    return [decorate_item(item, source.id, source_name, category_info["name"], labels) for item in items]


def dedupe(items: list[EvidenceItem]) -> list[EvidenceItem]:
    kept: list[EvidenceItem] = []
    seen_keys: set[str] = set()
    for item in items:
        tokens = unique_tokens(item.title)
        key = " ".join(sorted(tokens))
        if not key:
            key = item.title.lower()
        if item.url and item.url in seen_keys:
            continue
        if key in seen_keys:
            continue
        duplicate = False
        for prior in kept:
            prior_tokens = unique_tokens(prior.title)
            if not tokens or not prior_tokens:
                continue
            overlap = len(tokens & prior_tokens) / max(1, len(tokens | prior_tokens))
            if overlap >= 0.82:
                prior.metrics.setdefault("duplicates", []).append({"source": item.source, "url": item.url})
                duplicate = True
                break
        if duplicate:
            continue
        if item.url:
            seen_keys.add(item.url)
        seen_keys.add(key)
        kept.append(item)
    return kept


def source_weight(item: EvidenceItem) -> float:
    if item.source_id == "hackernews":
        return 1.15
    if item.source_id in {"producthunt-rss", "producthunt-api", "github-trending", "techmeme", "ai-products"}:
        return 1.05
    if item.source_id in {"global-search", "zhihu-search", "hot-list"}:
        return 1.05
    if item.source_id == "arxiv":
        return 1.0
    if item.source_id.startswith("blockbeats"):
        return 1.05
    return 0.8


def engagement_score(item: EvidenceItem) -> float:
    metrics = item.metrics or {}
    total = 0.0
    for key in ("points", "comments", "votes", "stars", "vote_up_count", "comment_count"):
        value = metrics.get(key) or 0
        try:
            total += float(value)
        except (TypeError, ValueError):
            pass
    return math.log1p(total) / 3.5


def relevance_score(item: EvidenceItem, topic: str | None, category_info: dict[str, Any]) -> float:
    text = f"{item.title} {item.summary}"
    tokens = unique_tokens(text)
    query_text = topic or " ".join(category_info.get("keywords", [])[:5])
    query = unique_tokens(query_text)
    if not query:
        return 0.5
    overlap = len(tokens & query)
    phrase_bonus = 1.0 if topic and topic.lower() in text.lower() else 0.0
    category_bonus = 0.4 if item.category == category_info.get("name") else 0.0
    return min(2.7, overlap / max(1, len(query)) * 2.0 + phrase_bonus + category_bonus)


def support_score(item: EvidenceItem, all_items: list[EvidenceItem]) -> float:
    tokens = unique_tokens(f"{item.title} {item.summary}")
    if not tokens:
        return 0.0
    sources: set[str] = set()
    for other in all_items:
        if other is item:
            continue
        other_tokens = unique_tokens(f"{other.title} {other.summary}")
        if len(tokens & other_tokens) >= 2:
            sources.add(other.source_id or other.source)
    return min(2.0, len(sources) * 0.5)


def score_items(items: list[EvidenceItem], topic: str | None, category_info: dict[str, Any], days: int) -> None:
    for item in items:
        recency = max(0.0, 1.0 - age_hours(item.published) / max(24.0, days * 24.0))
        item.score = round(
            source_weight(item)
            + engagement_score(item)
            + relevance_score(item, topic, category_info) * 1.8
            + support_score(item, items)
            + recency,
            3,
        )


def angle_for(item: EvidenceItem) -> str:
    text = f"{item.title} {item.summary}".lower()
    if any(word in text for word in ("paper", "arxiv", "benchmark", "research", "model", "论文", "研究")):
        return "研究转译"
    if any(word in text for word in ("launch", "show hn", "product", "github", "open source", "tool", "产品", "工具")):
        return "工具/产品拆解"
    if any(word in text for word in ("agent", "workflow", "automation", "browser", "coding", "工作流", "自动化")):
        return "工作流分析"
    if any(word in text for word in ("security", "privacy", "regulation", "policy", "risk", "风险", "监管")):
        return "风险与治理"
    if any(word in text for word in ("market", "liquidity", "yield", "etf", "macro", "市场", "流动性", "投资")):
        return "市场/商业分析"
    return "趋势观察"


def related_items(anchor: EvidenceItem, items: list[EvidenceItem], limit: int = 5) -> list[EvidenceItem]:
    anchor_tokens = unique_tokens(f"{anchor.title} {anchor.summary}")
    scored: list[tuple[int, float, EvidenceItem]] = []
    for item in items:
        if item is anchor:
            continue
        overlap = len(anchor_tokens & unique_tokens(f"{item.title} {item.summary}"))
        if overlap:
            scored.append((overlap, item.score, item))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [anchor] + [row[2] for row in scored[: limit - 1]]


def headline_seed(topic: str, item: EvidenceItem) -> str:
    angle = angle_for(item)
    if angle == "研究转译":
        return f"{topic}: 从最新研究看真正的变化"
    if angle == "工具/产品拆解":
        return f"{topic}: 新工具热度背后的可用工作流"
    if angle == "工作流分析":
        return f"{topic}: 从功能发布到工作方式迁移"
    if angle == "风险与治理":
        return f"{topic}: 热点背后的风险、边界与下一步"
    if angle == "市场/商业分析":
        return f"{topic}: 市场信号背后的真实变量"
    return f"{topic}: 为什么这个信号现在值得写"


def why_now(item: EvidenceItem) -> str:
    date = item.published[:10] if item.published else "无明确日期"
    metrics = []
    if item.metrics.get("points"):
        metrics.append(f"{item.metrics.get('points')} HN points")
    if item.metrics.get("comments"):
        metrics.append(f"{item.metrics.get('comments')} comments")
    if item.metrics.get("votes"):
        metrics.append(f"{item.metrics.get('votes')} votes")
    metric_text = f"，互动数据: {', '.join(metrics)}" if metrics else ""
    return f"{item.source} 在 {date} 出现相关信号{metric_text}。"


def reader_payoff(item: EvidenceItem) -> str:
    angle = angle_for(item)
    if angle == "研究转译":
        return "帮助读者把论文或技术信号翻译成可判断的产品/工作流影响。"
    if angle == "工具/产品拆解":
        return "帮助读者判断一个新工具是否值得试用、复刻或纳入现有流程。"
    if angle == "工作流分析":
        return "帮助读者看清工具变化如何改变实际工作步骤。"
    if angle == "风险与治理":
        return "帮助读者识别采用前需要处理的风险与边界。"
    if angle == "市场/商业分析":
        return "帮助读者从数据、资金流和叙事中分辨真正变量。"
    return "帮助读者从零散信息中抓住一个可操作的趋势。"


def build_candidates(items: list[EvidenceItem], topic: str | None, category_info: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    ranked = sorted(items, key=lambda item: item.score, reverse=True)
    for item in ranked[: max(limit, 3)]:
        evidence = related_items(item, ranked, limit=6)
        sources = sorted({entry.source for entry in evidence})
        topic_name = topic or item.title
        candidate = {
            "topic": topic_name,
            "category": category_info["name"],
            "angle": angle_for(item),
            "headline_seed": headline_seed(topic_name, item),
            "score": round(item.score + len(sources) * 0.4 + len(evidence) * 0.15, 3),
            "why_now": why_now(item),
            "reader_payoff": reader_payoff(item),
            "evidence_urls": [entry.url for entry in evidence if entry.url],
            "evidence_titles": [entry.title for entry in evidence],
            "sources": sources,
        }
        candidates.append(candidate)
    candidates.sort(key=lambda row: row["score"], reverse=True)
    return candidates[:limit]


def markdown_link(title: str, url: str) -> str:
    clean_title = title.replace("|", "\\|")
    return f"[{clean_title}]({url})" if url else clean_title


def render_source_refs(refs: list[SourceRef]) -> list[str]:
    if not refs:
        return ["- 无"]
    return [f"- `{ref.id}` ({ref.name}) - {ref.role} - {ref.description}" for ref in refs]


def render_skipped(skipped: list[dict[str, str]], errors: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in skipped:
        lines.append(f"- `{item['id']}` ({item['name']}) - {item['role']} - {item['reason']}")
    for error in errors:
        lines.append(f"- {error.get('source')}: {error.get('error')}")
    return lines or ["- 无"]


def render_brief(
    mode: str,
    topic: str | None,
    category_resolution: CategoryResolution,
    category_info: dict[str, Any],
    query_values: list[str],
    enabled_sources: list[SourceRef],
    skipped_sources: list[dict[str, str]],
    recommended_sources: list[SourceRef],
    writing_helpers: list[SourceRef],
    candidates: list[dict[str, Any]],
    items: list[EvidenceItem],
    errors: list[dict[str, Any]],
    created: dt.datetime,
) -> str:
    selected = candidates[0] if candidates else {}
    top_items = sorted(items, key=lambda item: item.score, reverse=True)[:12]
    lines = [
        "---",
        "type: blog-research-brief",
        f"mode: {mode}",
        f"topic: {json.dumps(topic or selected.get('topic', ''), ensure_ascii=False)}",
        f"category: {json.dumps(category_resolution.name, ensure_ascii=False)}",
        f"category_confidence: {category_resolution.confidence}",
        f"created: {created.isoformat()}",
        f"source_count: {len(items)}",
        f"selected_angle: {json.dumps(selected.get('angle', ''), ensure_ascii=False)}",
        "---",
        "",
        "# 博客研究简报",
        "",
        "## 分类与来源",
        "",
        f"- 主题分类: {category_resolution.name}",
        f"- 分类置信度: {category_resolution.confidence}",
        f"- 分类方式: {'显式指定' if category_resolution.explicit else '自动推断'}",
        f"- 匹配关键词: {', '.join(category_resolution.matched_keywords) if category_resolution.matched_keywords else '无'}",
        f"- 查询变体: {', '.join(query_values) if query_values else '无'}",
        "",
        "### 已启用自动源",
        "",
        *render_source_refs(enabled_sources),
        "",
        "### 跳过或失败的源",
        "",
        *render_skipped(skipped_sources, errors),
        "",
        "### 建议深挖源",
        "",
        *render_source_refs(recommended_sources),
    ]
    if writing_helpers:
        lines.extend(["", "### 写作增强建议", "", *render_source_refs(writing_helpers)])

    lines.extend(
        [
            "",
            "## 选题判断",
            "",
            f"- 推荐标题种子: {selected.get('headline_seed', '暂无')}",
            f"- 推荐角度: {selected.get('angle', '暂无')}",
            f"- 为什么现在写: {selected.get('why_now', '暂无')}",
            f"- 读者收益: {selected.get('reader_payoff', '暂无')}",
            "",
            "## 候选选题",
            "",
        ]
    )
    if candidates:
        for index, candidate in enumerate(candidates[:5], 1):
            lines.extend(
                [
                    f"{index}. **{candidate['headline_seed']}**",
                    f"   - score: {candidate['score']}",
                    f"   - sources: {', '.join(candidate['sources'])}",
                    f"   - payoff: {candidate['reader_payoff']}",
                ]
            )
    else:
        lines.append("- 暂无候选选题；需要补充可用源或更明确的话题。")

    lines.extend(
        [
            "",
            "## 证据包",
            "",
            "| Score | Source | Category | Date | Evidence | Why it matters |",
            "| ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for item in top_items:
        date = item.published[:10] if item.published else ""
        why = item.summary[:160] or ", ".join(item.labels)
        lines.append(
            f"| {item.score:.2f} | {item.source} | {item.category} | {date} | {markdown_link(item.title, item.url)} | {why.replace('|', '/')} |"
        )
    if not top_items:
        lines.append("| 0 | 无 | - | - | 无证据 | 请查看跳过源并补充凭据或换用深挖源 |")

    lines.extend(
        [
            "",
            "## 建议大纲",
            "",
            "1. 用一个具体变化开场: 谁在什么时候发布/讨论/采用了什么。",
            "2. 解释它为什么不是孤立事件: 引用 2-3 个跨来源证据。",
            "3. 提炼真正的变化: 产品、工作流、研究方向、市场变量或用户行为迁移。",
            "4. 给出读者可执行判断: 是否关注、如何试用、如何验证、什么时候暂缓。",
            "5. 写出限制、反证和下一步观察点。",
            "",
            "## 缺口与风险",
            "",
            "- 检查是否存在一手来源不足的问题。",
            "- 检查是否过度依赖单一社区热度。",
            "- 检查当前分类下是否缺少社区反馈、原始文档或反方证据。",
            "- 时间敏感内容必须补充精确日期和最新核验。",
        ]
    )
    return "\n".join(lines) + "\n"


def resolve_article_type(
    topic: str | None,
    angle: str,
    category_name: str,
    explicit_type: str | None = None,
) -> ArticleTypeResolution:
    if explicit_type:
        if explicit_type not in ARTICLE_TYPES:
            raise ValueError(f"Unknown article type: {explicit_type}. Valid types: {', '.join(ARTICLE_TYPES)}")
        return ArticleTypeResolution(explicit_type, "由 --article-type 显式指定。", 1.0, True)

    text = f"{topic or ''} {angle} {category_name}".lower()
    rules: list[tuple[str, tuple[str, ...], str, float]] = [
        ("comparison", (" vs ", "对比", "比较", "comparison", "替代方案", "哪个好"), "题目包含明确的对比或替代意图。", 0.92),
        ("case-study", ("案例", "复盘", "case study", "before and after", "前后变化"), "题目围绕具体案例、过程或结果复盘。", 0.9),
        ("listicle", ("清单", "榜单", "最佳", "top ", "best ", "推荐的", "个工具", "种方法"), "题目要求对多个选项进行筛选或排序。", 0.86),
        ("roundup", ("合集", "综述", "周报", "月报", "roundup", "本周", "本月", "观点汇总"), "题目需要汇总一个时间范围内的多个来源或观点。", 0.86),
        ("product-review", ("评测", "测评", "review", "上手体验", "值不值得", "产品发布"), "题目以单个产品的使用价值和限制为中心。", 0.88),
        ("tutorial", ("教程", "代码", "编程", "部署", "安装", "配置", "api", "sdk", "debug", "实现一个", "技术分享"), "题目要求在明确技术环境中复现实现。", 0.87),
        ("pillar-page", ("完整指南", "系统地图", "从入门到", "全面理解", "百科", "知识体系"), "题目需要覆盖宽主题并建立系统导航。", 0.8),
        ("how-to-guide", ("如何", "怎么", "指南", "流程", "工作流", "how to", "步骤"), "题目具有明确的任务和操作意图。", 0.84),
        ("news-analysis", ("新闻", "发布", "宣布", "诉讼", "监管", "政策", "突发", "最新", "发生了什么", "lawsuit", "sues", "announces", "launches"), "题目由近期事件或政策变化触发。", 0.82),
        ("data-research", ("研究", "论文", "arxiv", "数据", "调查", "报告", "实验结果", "benchmark"), "题目以论文、数据或研究方法为核心证据。", 0.84),
        ("faq-knowledge", ("什么是", "常见问题", "faq", "问答", "入门问题"), "题目主要满足定义和高频问答需求。", 0.83),
    ]
    for name, tokens, reason, confidence in rules:
        if any(token in text for token in tokens):
            return ArticleTypeResolution(name, reason, confidence, False)
    return ArticleTypeResolution(
        "thought-leadership",
        "未发现更强的任务、比较、案例、新闻或研究意图，使用观点分析作为回退文体。",
        0.55,
        False,
    )


def validate_length_override(
    minimum_length: int | None,
    maximum_length: int | None,
    writer: str,
) -> tuple[int, int] | None:
    if minimum_length is None and maximum_length is None:
        return None
    if writer != "agent-packet":
        raise ValueError("--min-length and --max-length are only valid with --writer agent-packet")
    if minimum_length is None or maximum_length is None:
        raise ValueError("--min-length and --max-length must be provided together")
    if (
        not isinstance(minimum_length, int)
        or isinstance(minimum_length, bool)
        or not isinstance(maximum_length, int)
        or isinstance(maximum_length, bool)
    ):
        raise ValueError("--min-length and --max-length must be integers")
    if minimum_length <= 0 or maximum_length <= 0:
        raise ValueError("--min-length and --max-length must be positive integers")
    if minimum_length > maximum_length:
        raise ValueError("--min-length cannot be greater than --max-length")
    return minimum_length, maximum_length


def build_length_requirement(
    article_profile: dict[str, Any],
    override: tuple[int, int] | None,
) -> dict[str, Any]:
    if override:
        minimum_length, recommended_max_length = override
        source = "cli_override"
    else:
        minimum_length = int(article_profile["minimum_length"])
        recommended_max_length = int(article_profile["recommended_max_length"])
        source = "article_type_default"
    return {
        "unit": "effective_zh_length",
        "minimum": minimum_length,
        "recommended_maximum": recommended_max_length,
        "source": source,
        "minimum_enforcement": "needs_work_non_blocking",
        "maximum_enforcement": "informational_only",
        "count_after_stage": "humanizer",
        "exclusions": [
            "YAML frontmatter",
            "fenced code blocks and inline code",
            "Markdown URLs while retaining link anchor text",
            "HTML comments",
            "visual and internal-link placeholder lines",
            "the 来源记录 section and everything after it",
            "punctuation, whitespace, and Markdown syntax",
        ],
    }


def select_claude_blog_template(category_name: str, angle: str, topic: str) -> str:
    """Legacy deterministic-writer selector; preserved for CLI compatibility."""
    text = f"{category_name} {angle} {topic}".lower()
    if any(token in text for token in ("如何", "how to", "教程", "workflow", "工作流", "技术分享")):
        return "how-to-guide"
    if any(token in text for token in ("vs", "对比", "comparison", "替代")):
        return "comparison"
    if any(token in text for token in ("产品", "product", "工具/产品")):
        return "product-review"
    if any(token in text for token in ("案例", "case", "复盘")):
        return "case-study"
    if any(token in text for token in ("市场", "投资", "经济", "web3", "新闻")):
        return "news-analysis"
    if any(token in text for token in ("研究", "论文", "arxiv", "data")):
        return "data-research"
    if any(token in text for token in ("什么是", "what is", "faq")):
        return "faq-knowledge"
    return "thought-leadership"


def category_audience(category_name: str) -> str:
    mapping = {
        "AI与智能体相关": "AI builder、产品团队、自动化工作流实践者",
        "Web3相关": "Web3 研究者、加密市场观察者、链上产品参与者",
        "经济主题": "关注宏观变量、产业变化和资产价格的人",
        "个人成长与认知": "想改进认知、习惯和长期学习系统的读者",
        "产品思维": "产品经理、创始人、独立开发者和用户研究者",
        "互联网与科技趋势": "技术从业者、投资观察者和互联网产品团队",
        "投资相关": "需要把叙事、数据和风险分开看的投资者",
        "职业发展": "正在做职业选择、转型、求职或能力建设的人",
        "商业与创业": "创始人、业务负责人、独立开发者和商业分析者",
        "技术分享": "工程师、技术负责人和希望复用实践的开发者",
        "哲学与思辨": "关心概念、价值判断和长期问题的读者",
        "社会观察": "关心公共议题、平台变化和社会心理的读者",
        "生活方式": "希望把消费、健康、时间和日常选择想清楚的人",
        "审美与文化": "关注文化产品、审美趋势和表达方式的读者",
        "旅行与城市": "关心城市体验、旅行选择和地方生活的人",
        "教育与学习系统": "学生、知识工作者、教师和自学者",
        "案例分析": "想通过具体案例理解决策、产品和组织的人",
    }
    return mapping.get(category_name, "需要从信息噪音中提炼判断的读者")


def safe_markdown_text(value: str, fallback: str = "") -> str:
    text = strip_html(value or fallback)
    return re.sub(r"\s+", " ", text).strip()


def compact_description(text: str, limit: int = 150) -> str:
    clean = safe_markdown_text(text)
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def evidence_as_fact(item: EvidenceItem, retrieved_date: str) -> dict[str, Any]:
    date = item.published[:10] if item.published else "未标明日期"
    title = safe_markdown_text(item.title, item.source)
    summary = safe_markdown_text(item.summary) or "该来源提供了一个可继续核验的外部信号。"
    claim = f"{date}，{item.source} 发布或收录了「{title}」这一信号。"
    return {
        "source": item.source,
        "source_id": item.source_id,
        "title": title,
        "url": item.url,
        "summary": summary,
        "published": item.published,
        "date": date,
        "labels": item.labels,
        "metrics": item.metrics,
        "score": item.score,
        "claim": claim,
        "retrieved": retrieved_date,
    }


def build_faq_plan(topic: str, category_name: str, angle: str) -> list[dict[str, str]]:
    return [
        {
            "question": f"{topic} 现在最值得关注的变化是什么？",
            "answer_direction": "先回答外部信号，再解释它对具体读者的决策影响。",
        },
        {
            "question": "这些证据足够支持强结论吗？",
            "answer_direction": "区分一手来源、社区热度和媒体转述，避免把热度写成确定趋势。",
        },
        {
            "question": f"如果我是{category_audience(category_name)}，下一步应该做什么？",
            "answer_direction": f"围绕{angle}给出一个低成本验证动作、一个观察指标和一个暂缓条件。",
        },
    ]


def build_claude_blog_packet(
    topic: str | None,
    category_resolution: CategoryResolution,
    category_info: dict[str, Any],
    candidates: list[dict[str, Any]],
    items: list[EvidenceItem],
    created: dt.datetime,
    language: str,
) -> dict[str, Any]:
    selected = candidates[0] if candidates else {}
    topic_name = str(topic or selected.get("topic") or category_resolution.name)
    title = str(selected.get("headline_seed") or f"{topic_name}: 从证据看一个值得追踪的变化")
    angle = str(selected.get("angle") or "趋势观察")
    retrieved_date = created.date().isoformat()
    ranked_items = sorted(items, key=lambda item: item.score, reverse=True)
    facts = [evidence_as_fact(item, retrieved_date) for item in ranked_items[:10]]
    source_names = sorted({item.source for item in ranked_items if item.source})
    labels = []
    for item in ranked_items:
        labels.extend(item.labels)
    tags = list(dict.fromkeys([category_resolution.name, angle, *labels]))[:8]
    keywords = list(dict.fromkeys([topic_name, *[str(value) for value in category_info.get("query_expansions", [])]]))[:6]
    template = select_claude_blog_template(category_resolution.name, angle, topic_name)
    return {
        "writer": "claude-blog",
        "language": language,
        "topic": topic_name,
        "title": title,
        "category": category_resolution.name,
        "category_confidence": category_resolution.confidence,
        "angle": angle,
        "template": template,
        "target_audience": category_audience(category_resolution.name),
        "primary_keyword": topic_name,
        "secondary_keywords": keywords[1:],
        "created": created.isoformat(),
        "retrieved": retrieved_date,
        "reader_payoff": selected.get("reader_payoff", "帮助读者从外部信号中形成可执行判断。"),
        "why_now": selected.get("why_now", "本次工作流收集到了一组新的外部信号。"),
        "source_coverage": {
            "item_count": len(items),
            "source_count": len(source_names),
            "sources": source_names,
        },
        "evidence": facts,
        "faq_plan": build_faq_plan(topic_name, category_resolution.name, angle),
        "visual_plan": [
            {"type": "cover", "description": f"{topic_name} 的抽象工作台或信息流视觉，适合 1200x630 hero"},
            {"type": "callout", "description": "证据强度分层，区分一手来源、社区信号和后续深挖"},
            {"type": "chart", "description": "按来源类型统计证据数量，可由后续人工或 strict delivery 渲染"},
        ],
        "internal_link_zones": [
            {"anchor": f"{category_resolution.name} 主题索引", "target": "对应主题的专题页或标签页"},
            {"anchor": f"{topic_name} 的深挖研究", "target": "后续使用 deep source 形成的研究文章"},
            {"anchor": "信息源矩阵工作流", "target": "介绍本工作流如何收集和筛选证据的说明页"},
        ],
        "source_records": [
            {
                "publisher": fact["source"],
                "title": fact["title"],
                "retrieved": fact["retrieved"],
                "url": fact["url"],
            }
            for fact in facts
            if fact["url"]
        ],
        "quality_constraints": [
            "所有依赖外部信息的判断必须带 inline Markdown link。",
            "没有可核验统计时，用来源信号、发布时间和出处描述，不编造数字。",
            "明确区分趋势、早期信号、反证和下一步观察点。",
            "保留 claude-blog 的 Key Takeaways、FAQ、引用胶囊、内链占位和视觉占位结构。",
        ],
    }


def evidence_requirement_coverage(
    requirements: list[dict[str, Any]],
    items: list[EvidenceItem],
) -> dict[str, list[dict[str, Any]]]:
    satisfied: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for requirement in requirements:
        terms = [str(term).lower() for term in requirement.get("match_any", [])]
        matches: list[dict[str, str]] = []
        for item in items:
            haystack = " ".join(
                [item.source, item.source_id, item.title, item.summary, *item.labels]
            ).lower()
            if terms and any(term in haystack for term in terms):
                matches.append({"source": item.source, "title": item.title, "url": item.url})
        result = {
            "id": requirement.get("id", "requirement"),
            "description": requirement.get("description", ""),
            "matches": matches[:5],
        }
        if matches:
            satisfied.append(result)
        else:
            missing.append(result)
    return {"satisfied": satisfied, "missing": missing}


def build_agent_writing_packet(
    topic: str | None,
    category_resolution: CategoryResolution,
    category_info: dict[str, Any],
    candidates: list[dict[str, Any]],
    items: list[EvidenceItem],
    created: dt.datetime,
    language: str,
    profiles: dict[str, Any],
    explicit_article_type: str | None,
    run_dir: Path,
    minimum_length: int | None = None,
    maximum_length: int | None = None,
) -> dict[str, Any]:
    selected = candidates[0] if candidates else {}
    topic_name = str(topic or selected.get("topic") or category_resolution.name)
    angle = str(selected.get("angle") or "趋势观察")
    resolution = resolve_article_type(topic_name, angle, category_resolution.name, explicit_article_type)
    base = build_claude_blog_packet(
        topic,
        category_resolution,
        category_info,
        candidates,
        items,
        created,
        language,
    )
    category_profile = profiles["categories"][category_resolution.name]
    article_profile = profiles["article_types"][resolution.name]
    length_override = validate_length_override(minimum_length, maximum_length, "agent-packet")
    length_requirement = build_length_requirement(article_profile, length_override)
    coverage = evidence_requirement_coverage(category_profile["evidence_requirements"], items)
    template_path = claude_blog_root() / "skills" / "blog" / "templates" / f"{resolution.name}.md"
    if not template_path.exists():
        raise ValueError(f"Article type template not found: {template_path}")
    humanizer_path = humanizer_skill_path()
    if not humanizer_path.exists():
        raise ValueError(f"Required humanizer skill not found: {humanizer_path}")
    humanizer_review_path = run_dir / "quality" / "humanizer-review.md"
    reader_payoff = str(base.get("reader_payoff") or "帮助读者形成可执行判断。")
    base.update(
        {
            "writer": "agent-packet",
            "template": resolution.name,
            "article_type": resolution.name,
            "article_type_explicit": resolution.explicit,
            "article_type_confidence": resolution.confidence,
            "type_selection_reason": resolution.reason,
            "template_path": str(template_path),
            "thesis_prompt": f"围绕“{topic_name}”提出一条可辩论且由证据支持的中心论点，最终让读者获得：{reader_payoff}",
            "category_profile": category_profile,
            "article_type_requirements": article_profile,
            "type_specific_outline": article_profile["outline"],
            "length_requirement": length_requirement,
            "required_evidence": category_profile["evidence_requirements"],
            "evidence_coverage": coverage,
            "unmet_requirements": [item["description"] for item in coverage["missing"]],
            "global_writing_rules": profiles["global_rules"],
            "humanizer": {
                "enabled": True,
                "skill": "humanizer-zh",
                "skill_path": str(humanizer_path),
                "stage": "after_initial_draft_before_validation",
                "review_path": str(humanizer_review_path),
                "preserve_exactly": [
                    "frontmatter fields and values",
                    "Markdown URLs and their source attribution",
                    "verified numbers, units, dates, names, and quotations",
                    "code blocks, inline code, commands, and configuration keys",
                    "the distinction between fact, inference, uncertainty, and evidence gaps",
                ],
                "instructions": [
                    "完整读取 humanizer-zh 的 SKILL.md，然后编辑 article.md，而不是只做关键词替换。",
                    "删除填充语、宣传语、模糊归因、否定式排比、机械三段式、过量破折号和聊天机器人痕迹。",
                    "改变句子与段落节奏，保留主题画像要求的语气，并用具体事实代替抽象判断。",
                    "只有用户或来源提供了真实个人经历时才使用第一人称经历；不得虚构体验、情绪、测试或采访。",
                    "编辑后逐项复核链接、数字、日期、引语、代码和证据强度没有变化。",
                    "把完成状态、主要改动和事实保护清单写入 review_path；本工作流不要求主观数字评分。",
                ],
                "review_schema": {
                    "required_status": "completed",
                    "required_sections": ["主要修改", "事实保护"],
                    "fact_checklist": [
                        "链接未改变",
                        "数字和日期未改变",
                        "引语和代码未改变",
                        "未虚构个人经历",
                    ],
                },
            },
            "quality_constraints": [
                *profiles["global_rules"],
                f"采用“{category_profile['voice']}”的表达方式。",
                *[f"必须完成：{move}" for move in category_profile["required_moves"]],
                *[f"禁止：{move}" for move in category_profile["prohibited_moves"]],
                f"风险说明：{category_profile['risk_disclosure']}",
                "主题画像和证据真实性高于模板中的 SEO、字数或统计要求。",
                (
                    f"最终正文有效字数至少 {length_requirement['minimum']}，建议不超过 "
                    f"{length_requirement['recommended_maximum']}；不得通过重复、空话或无来源内容凑字数。"
                ),
            ],
            "agent_handoff": {
                "article_path": str(run_dir / "article.md"),
                "instructions": [
                    "完整读取 writing_packet.json、brief.md、sources.json 和 template_path 指向的文体模板。",
                    "先确定一条中心论点，再按文体结构组织证据；不得逐条摘要来源。",
                    "完成 article.md 初稿，不复制 legacy deterministic writer 的通用套话。",
                    "缺失证据只能标为缺口或有限信号，不得为了满足模板编造数字、测试或经历。",
                    (
                        f"以 length_requirement 的 {length_requirement['minimum']}-"
                        f"{length_requirement['recommended_maximum']} 有效字数区间组织初稿；建议上限只作写作目标。"
                    ),
                    "初稿完成后，完整读取 humanizer.skill_path 并按 humanizer.instructions 编辑 article.md。",
                    "写入 humanizer.review_path，记录主要修改并逐项勾选事实保护清单，不做主观数字评分。",
                    "Humanizer 编辑完成后运行 validation_command，检查最终稿的事实、结构、主题画像、文体和最低有效字数。",
                ],
                "validation_command": f"{sys.executable} {Path(__file__).resolve()} --validate-run {run_dir}",
            },
        }
    )
    return base


def run_process(cmd: list[str], timeout: float, cwd: Path | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False, cwd=cwd)
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "ok": proc.returncode == 0,
        }
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc), "ok": False}


def local_analyze_payload(article_path: Path, article_text: str, script_error: dict[str, Any]) -> dict[str, Any]:
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", article_text, count=1, flags=re.DOTALL)
    words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", body)
    h1_count = len(re.findall(r"^# ", body, flags=re.MULTILINE))
    h2_count = len(re.findall(r"^## ", body, flags=re.MULTILINE))
    links = markdown_urls(body)
    has_takeaways = "核心要点" in body or "Key Takeaways" in body
    has_faq = "Frequently Asked Questions" in body
    has_sources = "## 来源记录" in body
    score = 40
    score += 10 if h1_count == 1 else 0
    score += min(15, h2_count * 2)
    score += 10 if has_takeaways else 0
    score += 10 if has_faq else 0
    score += 10 if has_sources else 0
    score += min(15, len(links))
    return {
        "status": "fallback",
        "reason": "claude-blog analyze_blog.py failed; local structural fallback was used",
        "script_error": {
            "returncode": script_error.get("returncode"),
            "stderr": script_error.get("stderr", "")[:2000],
            "stdout": script_error.get("stdout", "")[:2000],
        },
        "file": str(article_path),
        "score": min(100, score),
        "metrics": {
            "word_like_token_count": len(words),
            "h1_count": h1_count,
            "h2_count": h2_count,
            "external_link_count": len(links),
            "has_key_takeaways": has_takeaways,
            "has_faq": has_faq,
            "has_source_records": has_sources,
        },
    }


def run_analyze_check(article_path: Path, quality_dir: Path, timeout: float) -> dict[str, Any]:
    script = claude_blog_root() / "scripts" / "analyze_blog.py"
    output_path = quality_dir / "analyze.json"
    if not script.exists():
        data = {"status": "skipped", "reason": f"script not found: {script}"}
        write_json(output_path, data)
        return {"status": "skipped", "path": str(output_path), "reason": data["reason"]}
    result = run_process(
        [sys.executable, str(script), str(article_path), "--format", "json"],
        timeout=max(30.0, timeout * 2),
        cwd=project_root(),
    )
    if result["ok"]:
        try:
            payload = json.loads(result["stdout"])
        except json.JSONDecodeError:
            payload = {"status": "raw", "stdout": result["stdout"], "stderr": result["stderr"]}
    else:
        payload = local_analyze_payload(article_path, article_path.read_text(encoding="utf-8"), result)
    write_json(output_path, payload)
    return {
        "status": "passed" if result["ok"] else "fallback",
        "path": str(output_path),
        "returncode": result["returncode"],
    }


def markdown_urls(text: str) -> list[str]:
    urls = re.findall(r"\]\((https?://[^)\s]+)\)", text)
    urls.extend(re.findall(r"(?<!\()https?://[^\s<>)]+", text))
    cleaned = [url.rstrip(".,;，。；)") for url in urls]
    return list(dict.fromkeys(cleaned))


def count_effective_article_length(article_text: str) -> dict[str, int]:
    text = re.sub(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", "", article_text, count=1, flags=re.DOTALL)
    source_heading = re.search(r"^##\s+来源记录\s*$", text, flags=re.MULTILINE)
    if source_heading:
        text = text[: source_heading.start()]
    text = re.sub(r"```.*?(?:```|\Z)|~~~.*?(?:~~~|\Z)", " ", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?(?:-->|\Z)", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(
        r"^\s*\[(?:INTERNAL-LINK|IMAGE|CHART|CALLOUT|VISUAL|STAT|TABLE)[^\]]*\]\s*$",
        " ",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://[^\s<>)]+", " ", text)
    cjk_count = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text))
    english_word_count = len(
        re.findall(r"(?<![A-Za-z0-9])(?:[A-Za-z]+(?:['’-][A-Za-z]+)*)(?![A-Za-z0-9])", text)
    )
    number_count = len(re.findall(r"(?<![A-Za-z0-9])\d+(?:[.,]\d+)*%?(?![A-Za-z0-9])", text))
    return {
        "effective_length": cjk_count + english_word_count + number_count,
        "cjk_characters": cjk_count,
        "english_words": english_word_count,
        "number_sequences": number_count,
    }


def semantic_section_present(article_text: str, section: str) -> bool:
    candidates = [part.strip() for part in re.split(r"[与或、/（）()]+", section) if len(part.strip()) >= 2]
    return any(candidate in article_text for candidate in candidates)


def render_writing_compliance_report(
    article_text: str,
    packet: dict[str, Any],
    article_path: Path,
) -> tuple[str, dict[str, Any]]:
    category = str(packet.get("category") or "")
    article_type = str(packet.get("article_type") or packet.get("template") or "")
    category_profile = packet.get("category_profile") or {}
    type_profile = packet.get("article_type_requirements") or {}
    length_requirement = packet.get("length_requirement") or {}
    length_result: dict[str, Any] | None = None
    checks: list[dict[str, Any]] = []

    def add_check(scope: str, check_id: str, description: str, ok: bool, details: str) -> None:
        checks.append(
            {
                "scope": scope,
                "id": check_id,
                "description": description,
                "ok": ok,
                "details": details,
            }
        )

    external_links = markdown_urls(article_text)
    add_check("global", "inline_sources", "至少三个外部来源链接", len(external_links) >= 3, f"found {len(external_links)}")
    has_exact_date = bool(
        re.search(r"\b20\d{2}-\d{2}-\d{2}\b|20\d{2}年\d{1,2}月(?:\d{1,2}日)?", article_text)
    )
    add_check("global", "exact_date", "时间敏感内容包含准确日期", has_exact_date, "present" if has_exact_date else "missing")
    limitation_terms = ("限制", "局限", "反方", "反证", "风险", "失败", "替代解释")
    has_limitation = any(term in article_text for term in limitation_terms)
    add_check("global", "limitations", "包含限制、反方或替代解释", has_limitation, "present" if has_limitation else "missing")

    if length_requirement:
        counts = count_effective_article_length(article_text)
        minimum = int(length_requirement.get("minimum", 0))
        recommended_maximum = int(length_requirement.get("recommended_maximum", minimum))
        actual = counts["effective_length"]
        if actual < minimum:
            position = "below_minimum"
        elif actual > recommended_maximum:
            position = "above_recommended_maximum"
        else:
            position = "within_range"
        minimum_ok = actual >= minimum
        add_check(
            "article_type",
            "minimum_length",
            f"最终正文有效字数不少于 {minimum}",
            minimum_ok,
            f"actual {actual}; recommended maximum {recommended_maximum}; {position}",
        )
        add_check(
            "article_type",
            "recommended_maximum",
            f"建议上限 {recommended_maximum}（仅供参考）",
            True,
            f"actual {actual}; {position}; overage never marks needs_work",
        )
        length_result = {
            **counts,
            "minimum": minimum,
            "recommended_maximum": recommended_maximum,
            "source": length_requirement.get("source", "article_type_default"),
            "position": position,
            "minimum_status": "passed" if minimum_ok else "needs_work",
            "maximum_status": "informational",
            "count_after_stage": length_requirement.get("count_after_stage", "humanizer"),
        }

    for check in category_profile.get("validation_checks", []):
        terms = [str(term) for term in check.get("any_terms", [])]
        matched = [term for term in terms if term in article_text]
        add_check(
            "category",
            str(check.get("id") or "category_check"),
            str(check.get("description") or "主题要求"),
            bool(matched),
            f"matched: {', '.join(matched[:5])}" if matched else f"expected one of: {', '.join(terms)}",
        )

    for index, section in enumerate(type_profile.get("outline", []), 1):
        present = semantic_section_present(article_text, str(section))
        add_check(
            "article_type",
            f"outline_{index}",
            f"覆盖文体章节：{section}",
            present,
            "present" if present else "missing semantic heading/content",
        )

    evidence_coverage = packet.get("evidence_coverage") or {}
    for requirement in evidence_coverage.get("satisfied", []):
        add_check(
            "evidence",
            str(requirement.get("id") or "evidence"),
            str(requirement.get("description") or "证据要求"),
            True,
            f"{len(requirement.get('matches', []))} matching source(s)",
        )
    for requirement in evidence_coverage.get("missing", []):
        add_check(
            "evidence",
            str(requirement.get("id") or "evidence"),
            str(requirement.get("description") or "证据要求"),
            False,
            "missing from research packet; report-only",
        )

    failed = [check for check in checks if not check["ok"]]
    status = "passed" if not failed else "needs_work"
    lines = [
        f"## Writing Compliance Report: {article_path.name}",
        "",
        f"**Category**: {category}",
        f"**Article type**: {article_type}",
        *(
            [
                f"**Effective length**: {length_result['effective_length']} / minimum {length_result['minimum']} / recommended maximum {length_result['recommended_maximum']}",
                f"**Length rule source**: {length_result['source']} ({length_result['position']})",
            ]
            if length_result
            else []
        ),
        f"**Overall**: {status} ({len(checks) - len(failed)}/{len(checks)} checks passed)",
        "**Delivery behavior**: report-only; failures do not block normal delivery",
        "",
        "| Scope | Check | Status | Details |",
        "|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['scope']} | {check['description'].replace('|', '/')} | "
            f"{'PASS' if check['ok'] else 'NEEDS WORK'} | {check['details'].replace('|', '/')} |"
        )
    lines.extend(
        [
            "",
            "### Notes",
            "- 主题画像与事实真实性高于模板中的 SEO、字数和统计要求。",
            "- 缺失证据必须在正文中降级为有限信号或明确缺口，不能由写作者补造。",
        ]
    )
    return "\n".join(lines) + "\n", {
        "status": status,
        "passed": len(checks) - len(failed),
        "total": len(checks),
        "failed": [check["id"] for check in failed],
        "length": length_result,
    }


def humanizer_pattern_findings(article_text: str) -> list[dict[str, Any]]:
    patterns = [
        (
            "promotional_language",
            "宣传或夸大措辞",
            r"至关重要|关键性的|充满活力|令人叹为观止|开创性的|不可磨灭|不断演变的格局|持久的证明",
            2,
        ),
        (
            "vague_attribution",
            "模糊归因",
            r"行业报告显示|观察者指出|专家认为|一些批评者认为|多个来源(?:显示|指出|认为)",
            0,
        ),
        (
            "ai_vocabulary",
            "高频 AI 词汇",
            r"此外|深入探讨|彰显|赋能|相互作用|复杂性|宝贵的|展示了|体现了|强调了",
            5,
        ),
        (
            "negative_parallelism",
            "否定式排比",
            r"不仅仅是.{0,40}(?:而是|更是)|不仅.{0,40}而且",
            1,
        ),
        (
            "chat_trace",
            "聊天机器人交流痕迹",
            r"希望这对您有帮助|当然！|一定！|您说得完全正确|如果您想让我|请告诉我",
            0,
        ),
        (
            "generic_positive_ending",
            "空泛积极结尾",
            r"未来看起来光明|激动人心的时代即将到来|向正确方向迈出的重要一步|继续追求卓越",
            0,
        ),
    ]
    findings: list[dict[str, Any]] = []
    for finding_id, description, pattern, allowed in patterns:
        matches = re.findall(pattern, article_text, flags=re.DOTALL)
        if len(matches) > allowed:
            findings.append(
                {
                    "id": finding_id,
                    "description": description,
                    "count": len(matches),
                    "allowed": allowed,
                }
            )
    dash_count = article_text.count("——") + article_text.count("—")
    allowed_dashes = max(2, len(article_text) // 1500)
    if dash_count > allowed_dashes:
        findings.append(
            {"id": "em_dash", "description": "破折号使用过多", "count": dash_count, "allowed": allowed_dashes}
        )
    bold_list_count = len(re.findall(r"^\s*[-*]\s+\*\*[^*]+\*\*[：:]", article_text, flags=re.MULTILINE))
    if bold_list_count > 2:
        findings.append(
            {"id": "bold_vertical_list", "description": "内联粗体标题列表过多", "count": bold_list_count, "allowed": 2}
        )
    emoji_heading_count = len(
        re.findall(r"^#{1,6}\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]", article_text, flags=re.MULTILINE)
    )
    if emoji_heading_count:
        findings.append(
            {"id": "emoji_heading", "description": "标题使用装饰性表情", "count": emoji_heading_count, "allowed": 0}
        )
    return findings


def render_humanizer_check_report(
    article_text: str,
    packet: dict[str, Any],
    article_path: Path,
) -> tuple[str, dict[str, Any]]:
    humanizer = packet.get("humanizer") or {}
    review_path = article_path.parent / "quality" / "humanizer-review.md"
    review_text = review_path.read_text(encoding="utf-8") if review_path.exists() else ""
    status_completed = bool(re.search(r"(?:状态|status)\s*[:：]\s*completed\b", review_text, flags=re.IGNORECASE))
    has_change_summary = bool(
        re.search(
            r"(?:^|\n)(?:#{1,6}\s*)?主要修改\s*[:：]?\s*\n(?:\s*[-*]\s+.+(?:\n|$))+",
            review_text,
            flags=re.MULTILINE,
        )
    )
    checklist_items = (humanizer.get("review_schema") or {}).get("fact_checklist") or [
        "链接未改变",
        "数字和日期未改变",
        "引语和代码未改变",
        "未虚构个人经历",
    ]
    checklist_results = {
        str(item): bool(re.search(rf"[-*]\s*\[[xX]\]\s*{re.escape(str(item))}", review_text))
        for item in checklist_items
    }
    fact_preservation_checked = bool(checklist_results) and all(checklist_results.values())
    findings = humanizer_pattern_findings(article_text)
    checks = [
        {
            "id": "review_exists",
            "ok": review_path.exists(),
            "details": str(review_path) if review_path.exists() else "missing quality/humanizer-review.md",
        },
        {
            "id": "review_completed",
            "ok": status_completed,
            "details": "completed" if status_completed else "review must contain 状态: completed",
        },
        {
            "id": "change_summary",
            "ok": has_change_summary,
            "details": "recorded" if has_change_summary else "review must contain 主要修改 with at least one list item",
        },
        {
            "id": "fact_preservation",
            "ok": fact_preservation_checked,
            "details": "all items checked" if fact_preservation_checked else "unchecked: " + ", ".join(
                item for item, checked in checklist_results.items() if not checked
            ),
        },
        {
            "id": "pattern_scan",
            "ok": not findings,
            "details": "no threshold violations" if not findings else ", ".join(item["id"] for item in findings),
        },
    ]
    failed = [check["id"] for check in checks if not check["ok"]]
    result_status = "passed" if not failed else "needs_work"
    lines = [
        f"## Humanizer Check: {article_path.name}",
        "",
        f"**Skill**: {humanizer.get('skill', 'humanizer-zh')}",
        f"**Required stage**: {humanizer.get('stage', 'after_initial_draft_before_validation')}",
        f"**Overall**: {result_status}",
        "**Delivery behavior**: report-only; this scan does not replace the humanizer-zh editing pass",
        "",
        "| Check | Status | Details |",
        "|---|---|---|",
    ]
    for check in checks:
        lines.append(f"| {check['id']} | {'PASS' if check['ok'] else 'NEEDS WORK'} | {check['details']} |")
    lines.extend(["", "### Pattern findings", ""])
    if findings:
        for finding in findings:
            lines.append(
                f"- {finding['description']}: {finding['count']} occurrence(s), allowed {finding['allowed']}."
            )
    else:
        lines.append("- 未发现超过阈值的常见 AI 写作模式。")
    lines.extend(
        [
            "",
            "### Fact-preservation reminder",
            "",
            "- Humanization must not change URLs, verified numbers, dates, quotations, code, or evidence strength.",
            "- First-person experience is allowed only when supplied by the user or a cited source.",
        ]
    )
    return "\n".join(lines) + "\n", {
        "status": result_status,
        "change_summary": has_change_summary,
        "fact_checklist": checklist_results,
        "review_path": str(review_path),
        "findings": findings,
        "failed": failed,
    }


def run_quality_checks(article_path: Path, packet: dict[str, Any], items: list[EvidenceItem], timeout: float) -> dict[str, Any]:
    quality_dir = article_path.parent / "quality"
    quality_dir.mkdir(parents=True, exist_ok=True)
    article_text = article_path.read_text(encoding="utf-8")
    checks: dict[str, Any] = {}
    checks["analyze"] = run_analyze_check(article_path, quality_dir, timeout)
    if packet.get("category_profile") and packet.get("article_type_requirements"):
        compliance_report, compliance_meta = render_writing_compliance_report(article_text, packet, article_path)
        compliance_path = quality_dir / "writing-compliance.md"
        compliance_path.write_text(compliance_report, encoding="utf-8")
        checks["writing_compliance"] = {**compliance_meta, "path": str(compliance_path)}
    if (packet.get("humanizer") or {}).get("enabled"):
        humanizer_report, humanizer_meta = render_humanizer_check_report(article_text, packet, article_path)
        humanizer_path = quality_dir / "humanizer-check.md"
        humanizer_path.write_text(humanizer_report, encoding="utf-8")
        checks["humanizer"] = {**humanizer_meta, "path": str(humanizer_path)}
    return checks


def run_strict_delivery(article_path: Path, packet: dict[str, Any], timeout: float) -> dict[str, Any]:
    root = claude_blog_root()
    scripts = {
        "generate_hero": root / "scripts" / "generate_hero.py",
        "blog_render": root / "scripts" / "blog_render.py",
        "blog_preflight": root / "scripts" / "blog_preflight.py",
    }
    missing = [name for name, path in scripts.items() if not path.exists()]
    if missing:
        return {"status": "blocked", "reason": f"missing claude-blog scripts: {', '.join(missing)}"}

    out_dir = article_path.parent
    command_timeout = max(60.0, timeout * 4)
    steps: list[dict[str, Any]] = []

    hero = run_process(
        [
            sys.executable,
            str(scripts["generate_hero"]),
            "--topic",
            str(packet.get("title", "")),
            "--tags",
            ",".join(packet.get("secondary_keywords", [])[:4]),
            "--out",
            str(out_dir),
            "--json",
        ],
        timeout=command_timeout,
        cwd=project_root(),
    )
    steps.append({"step": "generate_hero", "returncode": hero["returncode"], "stderr": hero["stderr"][:1000]})
    if not hero["ok"]:
        return {"status": "blocked", "reason": "hero generation failed", "steps": steps}

    hero_files = [
        path
        for path in out_dir.glob("hero.*")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} and path.name != "hero-credit.txt"
    ]
    hero_name = hero_files[0].name if hero_files else ""
    render_cmd = [
        sys.executable,
        str(scripts["blog_render"]),
        "--md",
        str(article_path),
        "--out-dir",
        str(out_dir),
        "--json",
    ]
    if hero_name:
        render_cmd.extend(["--hero", hero_name])
    render = run_process(render_cmd, timeout=command_timeout, cwd=project_root())
    steps.append({"step": "blog_render", "returncode": render["returncode"], "stderr": render["stderr"][:1000]})
    if not render["ok"]:
        return {"status": "blocked", "reason": "render failed", "steps": steps}

    nonce_init = run_process(
        [sys.executable, str(scripts["blog_preflight"]), "--draft", str(out_dir), "--init-review-nonce"],
        timeout=timeout,
        cwd=project_root(),
    )
    steps.append({"step": "init_review_nonce", "returncode": nonce_init["returncode"], "stderr": nonce_init["stderr"][:1000]})
    nonce_path = out_dir / ".review-nonce"
    if nonce_path.exists() and not (out_dir / "review.md").exists():
        nonce = nonce_path.read_text(encoding="utf-8").strip()
        (out_dir / "review.md").write_text(
            "\n".join(
                [
                    f"## Quality Review: {packet.get('title', article_path.name)}",
                    "",
                    "This workflow script cannot dispatch the claude-blog `blog-reviewer` agent by itself.",
                    "Run the reviewer agent or bypass strict delivery only after manual review.",
                    "",
                    f"Nonce: {nonce}",
                    "BLOCKING: true (blog-reviewer agent was not executed by this script)",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    preflight = run_process(
        [sys.executable, str(scripts["blog_preflight"]), "--draft", str(out_dir), "--strict", "--json"],
        timeout=command_timeout,
        cwd=project_root(),
    )
    steps.append({"step": "blog_preflight", "returncode": preflight["returncode"], "stderr": preflight["stderr"][:1000]})
    payload: dict[str, Any]
    try:
        payload = json.loads(preflight["stdout"]) if preflight["stdout"].strip() else {}
    except json.JSONDecodeError:
        payload = {"stdout": preflight["stdout"]}
    return {
        "status": "passed" if preflight["ok"] else "blocked",
        "reason": "all strict delivery gates passed" if preflight["ok"] else "strict delivery preflight blocked",
        "report": payload,
        "steps": steps,
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def collect_items(
    args: argparse.Namespace,
    config: dict[str, Any],
    category_resolution: CategoryResolution,
    category_info: dict[str, Any],
    errors: list[dict[str, Any]],
) -> tuple[str, list[EvidenceItem], list[SourceRef], list[dict[str, str]], list[SourceRef], list[SourceRef], list[str]]:
    mode = "topic" if args.topic else "auto"
    query_values = query_variants(args.topic, category_info)
    query = effective_query(args.topic, category_info)
    enabled, skipped, recommended, helpers = resolve_sources(config, category_info, mode, query)
    items: list[EvidenceItem] = []
    per_source = max(3, args.max_items // max(1, len(enabled)))
    for source in enabled:
        items.extend(
            run_collector(
                source,
                config,
                category_info,
                args.topic,
                query,
                mode,
                per_source,
                args.days,
                args.timeout,
                errors,
            )
        )

    if not items and enabled:
        fallback_ids = ["hackernews", "techmeme", "producthunt-rss", "github-trending"]
        for source_id in fallback_ids:
            if any(ref.id == source_id for ref in enabled):
                continue
            available, reason = check_source_availability(config, source_id, query)
            ref = source_ref(config, source_id, "empty-result-fallback")
            if not available:
                skipped.append(
                    {
                        "id": source_id,
                        "name": ref.name,
                        "role": ref.role,
                        "kind": ref.kind,
                        "reason": reason,
                    }
                )
                continue
            enabled.append(ref)
            items.extend(
                run_collector(
                    ref,
                    config,
                    category_info,
                    args.topic,
                    query,
                    mode,
                    max(3, args.max_items // 4),
                    args.days,
                    args.timeout,
                    errors,
                )
            )
            if items:
                break

    items = dedupe(items)
    score_items(items, args.topic, category_info, args.days)
    items.sort(key=lambda item: item.score, reverse=True)
    return mode, items[: args.max_items], enabled, skipped, recommended, helpers, query_values


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_evidence_items(path: Path) -> list[EvidenceItem]:
    payload = load_json(path)
    if not isinstance(payload, list):
        raise ValueError(f"Expected an evidence list in {path}")
    allowed = {field.name for field in dataclasses.fields(EvidenceItem)}
    return [EvidenceItem(**{key: value for key, value in item.items() if key in allowed}) for item in payload]


def validate_existing_run(run_dir: Path, timeout: float, strict_delivery_enabled: bool) -> int:
    run_dir = run_dir.expanduser().resolve()
    article_path = run_dir / "article.md"
    packet_path = run_dir / "writing_packet.json"
    sources_path = run_dir / "sources.json"
    metadata_path = run_dir / "metadata.json"
    missing = [str(path) for path in (article_path, packet_path, sources_path) if not path.exists()]
    if missing:
        print(json.dumps({"status": "error", "missing": missing}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    try:
        packet = load_json(packet_path)
        items = load_evidence_items(sources_path)
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    quality_checks = run_quality_checks(article_path, packet, items, timeout)
    strict_delivery = {"status": "skipped", "reason": "--strict-delivery not set"}
    exit_code = 0
    if strict_delivery_enabled:
        strict_delivery = run_strict_delivery(article_path, packet, timeout)
        if strict_delivery.get("status") == "blocked":
            exit_code = 1

    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        try:
            loaded = load_json(metadata_path)
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            metadata = {}
    metadata.update(
        {
            "writer": "agent-packet",
            "article_path": str(article_path),
            "writing_packet_path": str(packet_path),
            "article_type": packet.get("article_type"),
            "article_type_confidence": packet.get("article_type_confidence"),
            "article_type_explicit": packet.get("article_type_explicit"),
            "length_requirement": packet.get("length_requirement"),
            "quality_checks": quality_checks,
            "strict_delivery": strict_delivery,
            "validated_at": now_local().isoformat(),
        }
    )
    write_json(metadata_path, metadata)
    result = {
        "status": "validated" if exit_code == 0 else "blocked",
        "run_dir": str(run_dir),
        "article_path": str(article_path),
        "quality_checks": quality_checks,
        "strict_delivery": strict_delivery,
        "non_blocking_compliance": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect evidence and build a category-routed blog research brief.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--topic", help="User-provided blog topic or idea.")
    mode.add_argument("--auto", action="store_true", help="Discover a topic automatically from recent signals.")
    mode.add_argument("--validate-run", help="Validate an agent-written article in an existing run directory.")
    parser.add_argument("--category", help="Writing category. If omitted, inferred from --topic or defaulted for --auto.")
    parser.add_argument("--list-categories", action="store_true", help="List configured writing categories and sources.")
    parser.add_argument("--days", type=int, default=7, help="Recent time window for sources that support dates.")
    parser.add_argument("--max-items", type=int, default=36, help="Maximum normalized evidence items to keep.")
    parser.add_argument("--candidate-count", type=int, default=6, help="Number of candidates in scorecard.")
    parser.add_argument("--output-dir", help="Directory for run artifacts. Defaults to runs/<timestamp>-<slug>.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Network timeout per request in seconds.")
    parser.add_argument(
        "--writer",
        choices=["agent-packet"],
        default="agent-packet",
        help="Writing mode. agent-packet prepares a typed handoff for an orchestrating agent to write the article.",
    )
    parser.add_argument(
        "--article-type",
        choices=ARTICLE_TYPES,
        help="Explicitly select one of the 12 article types; otherwise inferred from topic and angle.",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        help="Override the minimum effective Chinese article length; requires --max-length and --writer agent-packet.",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        help="Override the recommended maximum effective length; requires --min-length and --writer agent-packet.",
    )
    parser.add_argument("--language", default="zh-CN", help="Article language for the final writer.")
    parser.add_argument(
        "--strict-delivery",
        action="store_true",
        help="Run the heavier delivery scripts during --validate-run after article.md exists. Blocks on failed gates.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        config = load_topic_config()
        profiles = load_writing_profiles(config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.list_categories:
        list_categories(config)
        return 0

    try:
        length_override = validate_length_override(args.min_length, args.max_length, args.writer)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.validate_run:
        return validate_existing_run(Path(args.validate_run), args.timeout, args.strict_delivery)

    if not args.topic and not args.auto:
        args.auto = True

    try:
        category_resolution = resolve_category(args.topic, args.category, config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    categories = category_map(config)
    category_info = categories[category_resolution.name]
    created = now_local()
    errors: list[dict[str, Any]] = []
    mode, items, enabled_sources, skipped_sources, recommended_sources, writing_helpers, queries = collect_items(
        args,
        config,
        category_resolution,
        category_info,
        errors,
    )
    candidates = build_candidates(items, args.topic, category_info, args.candidate_count) if items else []

    slug_source = args.topic or (candidates[0]["topic"] if candidates else category_resolution.name)
    run_id = f"{created.strftime('%Y%m%d-%H%M%S')}-{slugify(slug_source)}"
    out_dir = Path(args.output_dir) if args.output_dir else skill_dir() / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    write_json(out_dir / "sources.json", [item.to_dict() for item in items])
    write_json(out_dir / "scorecard.json", candidates)
    brief_text = render_brief(
        mode,
        args.topic,
        category_resolution,
        category_info,
        queries,
        enabled_sources,
        skipped_sources,
        recommended_sources,
        writing_helpers,
        candidates,
        items,
        errors,
        created,
    )
    (out_dir / "brief.md").write_text(brief_text, encoding="utf-8")

    article_path: Path | None = None
    writing_packet_path: Path | None = None
    article_type: str | None = None
    article_type_confidence: float | None = None
    article_type_explicit = False
    length_requirement: dict[str, Any] | None = None
    quality_checks: dict[str, Any] = {}
    strict_delivery: dict[str, Any] = {"status": "skipped", "reason": "--strict-delivery not set"}
    exit_code = 0

    packet = build_agent_writing_packet(
        args.topic,
        category_resolution,
        category_info,
        candidates,
        items,
        created,
        args.language,
        profiles,
        args.article_type,
        out_dir.resolve(),
        length_override[0] if length_override else None,
        length_override[1] if length_override else None,
    )
    writing_packet_path = out_dir / "writing_packet.json"
    write_json(writing_packet_path, packet)
    article_type = str(packet["article_type"])
    article_type_confidence = float(packet["article_type_confidence"])
    article_type_explicit = bool(packet["article_type_explicit"])
    length_requirement = packet["length_requirement"]
    if args.strict_delivery:
        strict_delivery = {
            "status": "skipped",
            "reason": "agent-packet must be written to article.md and validated with --validate-run before strict delivery",
        }

    metadata = {
        "mode": mode,
        "topic": args.topic,
        "category": category_resolution.name,
        "category_confidence": category_resolution.confidence,
        "category_explicit": category_resolution.explicit,
        "category_matched_keywords": category_resolution.matched_keywords,
        "query_variants": queries,
        "created": created.isoformat(),
        "days": args.days,
        "errors": errors,
        "enabled_sources": [source.to_dict() for source in enabled_sources],
        "skipped_sources": skipped_sources,
        "recommended_deep_sources": [source.to_dict() for source in recommended_sources],
        "writing_helpers": [source.to_dict() for source in writing_helpers],
        "item_count": len(items),
        "candidate_count": len(candidates),
        "writer": args.writer,
        "language": args.language,
        "article_type": article_type,
        "article_type_confidence": article_type_confidence,
        "article_type_explicit": article_type_explicit,
        "length_requirement": length_requirement,
        "article_path": str(article_path) if article_path else "",
        "writing_packet_path": str(writing_packet_path) if writing_packet_path else "",
        "quality_checks": quality_checks,
        "strict_delivery": strict_delivery,
    }
    write_json(out_dir / "metadata.json", metadata)

    result = {
        "run_dir": str(out_dir),
        "mode": mode,
        "category": category_resolution.name,
        "category_confidence": category_resolution.confidence,
        "item_count": len(items),
        "candidate_count": len(candidates),
        "selected": candidates[0] if candidates else None,
        "enabled_sources": [source.id for source in enabled_sources],
        "skipped_sources": skipped_sources,
        "errors": errors,
        "writer": args.writer,
        "article_type": article_type,
        "article_type_confidence": article_type_confidence,
        "article_type_explicit": article_type_explicit,
        "length_requirement": length_requirement,
        "article_path": str(article_path) if article_path else None,
        "writing_packet_path": str(writing_packet_path) if writing_packet_path else None,
        "quality_checks": quality_checks,
        "strict_delivery": strict_delivery,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
