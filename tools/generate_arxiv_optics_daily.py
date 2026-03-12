from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - optional dependency at runtime
    OpenAI = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "arxiv_optics_config.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Codex-ArXiv-Optics-Daily/1.0"
)
TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
DEEPSEEK_DEFAULT_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-chat"

TOPIC_KEYWORDS: dict[str, set[str]] = {
    "Integrated Optics": {
        "integrated optics",
        "integrated photonics",
        "integrated photonic",
        "photonic integrated circuit",
        "photonic integrated circuits",
        "silicon photonics",
        "on-chip photonic",
        "on chip photonic",
        "waveguide",
        "waveguides",
        "ring resonator",
        "ring resonators",
        "micro-ring",
        "microring",
        "guided-wave",
        "guided wave optics",
        "optical interconnect",
        "optical interconnects",
    },
    "Nonlinear Optics": {
        "nonlinear optics",
        "nonlinear optical",
        "second harmonic",
        "third harmonic",
        "harmonic generation",
        "sum-frequency",
        "sum frequency",
        "difference-frequency",
        "difference frequency",
        "four-wave mixing",
        "four wave mixing",
        "kerr",
        "self-phase modulation",
        "cross-phase modulation",
        "optical parametric",
        "parametric oscillation",
        "frequency conversion",
        "supercontinuum",
        "chi(2)",
        "chi(3)",
        "chi2",
        "chi3",
    },
    "Quantum Optics & Quantum Computing": {
        "quantum optics",
        "quantum optical",
        "quantum photonics",
        "cavity qed",
        "waveguide qed",
        "single-photon",
        "single photon",
        "single photons",
        "entangled photon",
        "entangled photons",
        "photon pair",
        "photon pairs",
        "squeezed light",
        "squeezed state of light",
        "spdc",
        "parametric down-conversion",
        "down-conversion",
        "down conversion",
        "quantum emitter",
        "quantum emitters",
        "photon blockade",
        "cavity optomechanics",
        "optomechanical",
        "linear optical quantum computing",
        "photonic quantum computing",
        "optical quantum computing",
        "boson sampling",
        "photonic qubit",
        "photonic qubits",
    },
    "Optical Computing": {
        "optical computing",
        "photonic computing",
        "optical computer",
        "photonic processor",
        "photonic processors",
        "optical neural network",
        "optical neural networks",
        "photonic neural network",
        "photonic neural networks",
        "optical accelerator",
        "photonic accelerator",
        "optical logic",
        "optical reservoir computing",
        "diffractive neural network",
        "diffractive optical network",
        "in-memory photonic",
        "neuromorphic photonics",
    },
    "Optical Imaging": {
        "optical imaging",
        "computational imaging",
        "optical microscopy",
        "microscopy",
        "holography",
        "holographic",
        "lensless imaging",
        "phase imaging",
        "fluorescence imaging",
        "super-resolution imaging",
        "super resolution imaging",
        "optical coherence tomography",
        "oct imaging",
        "endoscopic imaging",
        "imaging through scattering",
        "ptychography",
        "tomographic microscopy",
    },
    "Optical Materials": {
        "optical material",
        "optical materials",
        "photonic material",
        "photonic materials",
        "optical properties",
        "refractive index",
        "dielectric function",
        "permittivity",
        "plasmonic",
        "plasmonics",
        "metasurface",
        "metasurfaces",
        "photonic crystal",
        "photonic crystals",
        "polariton",
        "polaritons",
        "electro-optic",
        "electro optic",
        "photochromic",
        "photoluminescence",
        "luminescence",
    },
    "AMO Physics": {
        "atomic, molecular, and optical",
        "atomic, molecular and optical",
        "atomic molecular and optical",
        "atomic molecular optical",
        "amo physics",
        "laser cooling",
        "magneto-optical trap",
        "magneto optical trap",
        "optical tweezer",
        "optical tweezers",
        "optical lattice",
        "optical lattices",
        "optical clock",
        "optical clocks",
        "atomic clock",
        "atomic clocks",
        "atomic spectroscopy",
        "molecular spectroscopy",
        "precision spectroscopy",
        "rydberg",
        "neutral atom",
        "neutral atoms",
        "cold atom",
        "cold atoms",
        "ultracold atom",
        "ultracold atoms",
        "trapped ion",
        "trapped ions",
        "ion trap",
        "ion traps",
        "atom-light interaction",
        "atom-light interactions",
    },
}

GENERAL_OPTICS_KEYWORDS = {
    "photonics",
    "photonic",
    "nanophotonic",
    "nanophotonics",
    "fiber optics",
    "laser",
    "lasers",
    "frequency comb",
    "frequency combs",
    "microcomb",
    "microcombs",
    "optics",
    "optical",
    "light-matter",
    "light matter",
}

EXCLUSION_KEYWORDS = {
    "optical theorem",
}

SUMMARY_ACTION_HINTS = (
    "we propose",
    "we present",
    "we demonstrate",
    "we show",
    "here we",
    "this work",
    "this paper",
    "our work",
    "we introduce",
    "we report",
    "we realize",
)


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def log(message: str) -> None:
    print(message, flush=True)


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("–", "-").replace("—", "-").replace("’", "'")
    return clean_space(lowered)


def parse_new_submissions(category: str, html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    dl = soup.select_one("dl#articles")
    if dl is None:
        raise ValueError(f"Could not find article list for {category}")

    first_section = dl.find("h3")
    if first_section is None:
        raise ValueError(f"Could not find section header for {category}")

    papers: list[dict[str, Any]] = []
    current = first_section.find_next_sibling()
    while current is not None and current.name != "h3":
        if current.name == "dt":
            link = current.find("a", title="Abstract")
            dd = current.find_next_sibling("dd")
            if link is None or dd is None:
                current = current.find_next_sibling()
                continue

            paper_id = clean_space(link.get_text(" ", strip=True)).replace("arXiv:", "")
            title_el = dd.select_one(".list-title")
            abstract_el = dd.select_one("p.mathjax")
            if title_el is None or abstract_el is None:
                current = current.find_next_sibling()
                continue

            authors = [
                {"name": clean_space(author.get_text(" ", strip=True))}
                for author in dd.select(".list-authors a")
                if clean_space(author.get_text(" ", strip=True))
            ]
            subjects_el = dd.select_one(".list-subjects")
            subjects_text = ""
            if subjects_el is not None:
                subjects_text = clean_space(
                    subjects_el.get_text(" ", strip=True).replace("Subjects:", "")
                )

            papers.append(
                {
                    "id": paper_id,
                    "category": category,
                    "title": clean_space(
                        title_el.get_text(" ", strip=True).replace("Title:", "")
                    ),
                    "abstract": clean_space(abstract_el.get_text(" ", strip=True)),
                    "url": f"https://arxiv.org/abs/{paper_id}",
                    "authors": authors,
                    "subjects": subjects_text,
                    "author_count": len(authors),
                }
            )
        current = current.find_next_sibling()

    return papers


def split_sentences(text: str) -> list[str]:
    pieces = re.split(r"(?<=[.!?。！？])\s*", text)
    return [clean_space(part) for part in pieces if clean_space(part)]


def first_sentence(text: str) -> str:
    sentences = split_sentences(text)
    return sentences[0] if sentences else clean_space(text)


def choose_summary_sentence(abstract: str) -> str:
    sentences = split_sentences(abstract)
    if not sentences:
        return clean_space(abstract)

    for sentence in sentences:
        lowered = normalize(sentence)
        if any(hint in lowered for hint in SUMMARY_ACTION_HINTS):
            return sentence

    for sentence in sentences:
        if len(sentence.split()) >= 10:
            return sentence

    return sentences[0]


def translate_text(
    text: str,
    target_lang: str,
    cache: dict[tuple[str, str], str | None],
    enabled: bool,
) -> str | None:
    if not enabled:
        return None

    cache_key = (text, target_lang)
    if cache_key in cache:
        return cache[cache_key]

    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": target_lang,
            "dt": "t",
            "q": text,
        }
    )
    url = f"{TRANSLATE_ENDPOINT}?{query}"
    try:
        payload = fetch_text(url, timeout=20)
        data = json.loads(payload)
        translated = "".join(item[0] for item in data[0] if item and item[0]).strip()
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, ValueError):
        translated = None

    cache[cache_key] = translated
    return translated


def find_keyword_hits(text: str, keywords: set[str]) -> list[str]:
    return sorted(keyword for keyword in keywords if keyword in text)


def classify_optics_topics(text: str) -> tuple[list[str], dict[str, list[str]]]:
    normalized = normalize(text)
    hits: dict[str, list[str]] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        matched = find_keyword_hits(normalized, keywords)
        if matched:
            hits[topic] = matched

    if hits:
        return list(hits.keys()), hits

    if any(keyword in normalized for keyword in EXCLUSION_KEYWORDS):
        return [], {}

    general_hits = find_keyword_hits(normalized, GENERAL_OPTICS_KEYWORDS)
    if len(general_hits) >= 2:
        hits["Other Optics"] = general_hits[:4]
        return ["Other Optics"], hits

    return [], {}


def build_deepseek_client(config: dict[str, Any]) -> Any | None:
    if not bool(config.get("enable_deepseek_summaries", True)):
        return None

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    if OpenAI is None:
        return None

    base_url = str(config.get("deepseek_base_url", DEEPSEEK_DEFAULT_BASE_URL)).strip()
    return OpenAI(api_key=api_key, base_url=base_url)


def strip_json_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def request_deepseek_summaries(
    client: Any,
    model: str,
    paper: dict[str, Any],
    topics: list[str],
) -> dict[str, Any] | None:
    topic_hint = ", ".join(topics) if topics else "None"
    prompt = f"""
Return a json object with exactly these keys:
- summary_en
- summary_zh
- summary_ja

Requirements:
- Each value must be exactly one sentence.
- summary_en must be in English.
- summary_zh must be in Simplified Chinese.
- summary_ja must be in Japanese.
- Keep the science faithful to the paper.
- Do not add markdown.
- Do not add extra keys.

Topic hints: {topic_hint}

Title: {paper["title"]}
Abstract: {paper["abstract"]}
""".strip()

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "You are a careful research assistant. Return valid json only.",
            },
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=500,
        stream=False,
    )

    content = response.choices[0].message.content if response.choices else ""
    if not content:
        return None

    return json.loads(strip_json_fence(content))


def fallback_summary_bundle(
    abstract: str,
    cache: dict[tuple[str, str], str | None],
    enable_translation: bool,
) -> dict[str, str]:
    english = choose_summary_sentence(abstract)
    chinese = translate_text(english, "zh-CN", cache, enable_translation) or english
    japanese = translate_text(english, "ja", cache, enable_translation) or english
    return {
        "en": first_sentence(english),
        "zh": first_sentence(chinese),
        "ja": first_sentence(japanese),
    }


def build_summary_bundle(
    paper: dict[str, Any],
    topics: list[str],
    cache: dict[tuple[str, str], str | None],
    enable_translation: bool,
    deepseek_client: Any | None,
    deepseek_model: str,
) -> tuple[dict[str, str], str]:
    fallback = fallback_summary_bundle(paper["abstract"], cache, enable_translation)
    if deepseek_client is None:
        return fallback, "fallback"

    try:
        payload = request_deepseek_summaries(deepseek_client, deepseek_model, paper, topics)
    except Exception:
        return fallback, "fallback"

    if not payload:
        return fallback, "fallback"

    english = first_sentence(str(payload.get("summary_en", "")).strip()) or fallback["en"]
    chinese = first_sentence(str(payload.get("summary_zh", "")).strip()) or (
        translate_text(english, "zh-CN", cache, enable_translation) or fallback["zh"]
    )
    japanese = first_sentence(str(payload.get("summary_ja", "")).strip()) or (
        translate_text(english, "ja", cache, enable_translation) or fallback["ja"]
    )

    return {
        "en": english,
        "zh": chinese,
        "ja": japanese,
    }, "deepseek"


def pick_featured_authors(authors: list[dict[str, str]], max_authors: int) -> list[dict[str, str]]:
    if len(authors) <= max_authors:
        return authors
    head = max_authors // 2
    tail = max_authors - head
    return authors[:head] + authors[-tail:]


def filter_and_enrich(
    papers: list[dict[str, Any]],
    enable_translation: bool,
    max_authors_shown: int,
    deepseek_client: Any | None,
    deepseek_model: str,
) -> list[dict[str, Any]]:
    translation_cache: dict[tuple[str, str], str | None] = {}
    kept: list[dict[str, Any]] = []

    for index, paper in enumerate(papers, start=1):
        log(f"      -> checking paper {index}/{len(papers)}: {paper['category']} {paper['id']}")
        combined_text = " ".join(
            [paper["title"], paper["abstract"], paper.get("subjects", "")]
        )
        topics, topic_hits = classify_optics_topics(combined_text)
        if not topics:
            continue

        summaries, summary_source = build_summary_bundle(
            paper=paper,
            topics=topics,
            cache=translation_cache,
            enable_translation=enable_translation,
            deepseek_client=deepseek_client,
            deepseek_model=deepseek_model,
        )

        kept.append(
            {
                **paper,
                "topics": topics,
                "topic_hits": topic_hits,
                "featured_authors": pick_featured_authors(
                    paper.get("authors", []), max_authors_shown
                ),
                "summaries": summaries,
                "summary_source": summary_source,
            }
        )

    return kept


def build_daily_html(date_str: str, papers: list[dict[str, Any]], categories: list[str]) -> str:
    papers_json = json.dumps(papers, ensure_ascii=False).replace("</", "<\\/")
    category_json = json.dumps(categories, ensure_ascii=False).replace("</", "<\\/")
    topic_order = list(TOPIC_KEYWORDS.keys()) + ["Other Optics"]
    topic_json = json.dumps(topic_order, ensure_ascii=False).replace("</", "<\\/")
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArXiv Optics Daily - __DATE__</title>
  <style>
    :root {
      --bg: #f2ece4;
      --panel: rgba(255, 252, 247, 0.94);
      --line: rgba(62, 45, 30, 0.14);
      --text: #2c221c;
      --muted: #6f5e50;
      --accent: #8a3f2d;
      --accent-2: #1c6270;
      --shadow: 0 18px 48px rgba(58, 38, 24, 0.12);
      --radius: 24px;
      --ui-font: "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
      --title-font: "Iowan Old Style", "Georgia", serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--ui-font);
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.82), transparent 34%),
        radial-gradient(circle at 84% 12%, rgba(28,98,112,0.12), transparent 22%),
        linear-gradient(180deg, #faf6ef 0%, var(--bg) 44%, #eee4d8 100%);
      min-height: 100vh;
    }
    .shell { width: min(1240px, calc(100% - 28px)); margin: 0 auto; padding: 28px 0 64px; }
    .hero {
      padding: 30px;
      border-radius: 30px;
      border: 1px solid var(--line);
      background:
        linear-gradient(135deg, rgba(255,255,255,0.9), rgba(255,248,240,0.76)),
        linear-gradient(135deg, rgba(138,63,45,0.08), rgba(28,98,112,0.08));
      box-shadow: var(--shadow);
    }
    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.82);
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    h1 {
      margin: 18px 0 10px;
      font-family: var(--title-font);
      font-size: clamp(34px, 5vw, 56px);
      line-height: 1.02;
      letter-spacing: -0.03em;
    }
    .hero p {
      margin: 0;
      max-width: 960px;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.72;
    }
    .stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 14px;
      margin-top: 24px;
    }
    .stat {
      padding: 16px 18px;
      border-radius: 18px;
      background: rgba(255,255,255,0.78);
      border: 1px solid var(--line);
    }
    .stat .label { color: var(--muted); font-size: 13px; margin-bottom: 6px; }
    .stat .value { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; }
    .controls {
      position: sticky;
      top: 12px;
      z-index: 3;
      margin-top: 22px;
      padding: 18px;
      border-radius: 24px;
      border: 1px solid var(--line);
      background: rgba(249, 243, 235, 0.92);
      backdrop-filter: blur(16px);
      box-shadow: 0 10px 24px rgba(58, 38, 24, 0.08);
    }
    .control-grid {
      display: grid;
      grid-template-columns: 1.4fr 1fr 1fr;
      gap: 16px;
    }
    .field { display: flex; flex-direction: column; gap: 10px; }
    .field label {
      font-size: 13px;
      font-weight: 700;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .search {
      width: 100%;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.92);
      color: var(--text);
      font: inherit;
    }
    .chip-row { display: flex; flex-wrap: wrap; gap: 10px; }
    .chip {
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.86);
      color: var(--text);
      font: inherit;
      cursor: pointer;
    }
    .chip.active {
      border-color: rgba(138,63,45,0.34);
      background: rgba(138,63,45,0.12);
      color: #5e2619;
    }
    .meta-row {
      margin-top: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      color: var(--muted);
      font-size: 14px;
    }
    .meta-row a { color: var(--accent); text-decoration: none; }
    .paper-grid {
      margin-top: 22px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
      gap: 18px;
    }
    .paper {
      display: flex;
      flex-direction: column;
      gap: 14px;
      padding: 22px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: 0 10px 24px rgba(58, 38, 24, 0.06);
    }
    .paper-top { display: flex; flex-wrap: wrap; gap: 8px; }
    .tag {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }
    .tag.category {
      background: rgba(44,34,28,0.08);
      color: var(--text);
    }
    .tag.topic {
      background: rgba(28,98,112,0.1);
      color: var(--accent-2);
      border: 1px solid rgba(28,98,112,0.14);
    }
    .paper .id { color: var(--muted); font-size: 13px; }
    .paper h2 {
      margin: 0;
      font-family: var(--title-font);
      font-size: 23px;
      line-height: 1.22;
      letter-spacing: -0.02em;
    }
    .paper h2 a { color: inherit; text-decoration: none; }
    .paper h2 a:hover { color: var(--accent); }
    .subtle {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.7);
    }
    .subtle .label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 8px;
    }
    .author-line,
    .subject-line,
    .abstract-line {
      margin: 0;
      font-size: 14px;
      line-height: 1.68;
    }
    .summary-grid {
      display: grid;
      gap: 10px;
    }
    .summary-item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,0.78);
    }
    .summary-item strong {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .summary-item p {
      margin: 0;
      font-size: 14px;
      line-height: 1.68;
    }
    details {
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.74);
      padding: 14px 16px;
    }
    details summary {
      cursor: pointer;
      list-style: none;
      color: var(--accent-2);
      font-weight: 700;
    }
    details summary::-webkit-details-marker { display: none; }
    details p {
      margin: 10px 0 0;
      font-size: 14px;
      line-height: 1.72;
    }
    .paper footer {
      margin-top: auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .paper footer a {
      color: var(--accent);
      text-decoration: none;
      font-weight: 700;
    }
    .empty {
      display: none;
      margin-top: 24px;
      padding: 28px;
      text-align: center;
      color: var(--muted);
      border-radius: 22px;
      border: 1px dashed var(--line);
      background: rgba(255,255,255,0.72);
    }
    @media (max-width: 980px) {
      .control-grid { grid-template-columns: 1fr; }
      .controls { position: static; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="eyebrow">ArXiv Optics Daily · __DATE__</div>
      <h1>Daily ArXiv Papers in Optics</h1>
      <p>
        Data comes from arXiv's daily <code>new submissions</code> pages across
        <code>cond-mat</code>, <code>physics</code>, <code>quant-ph</code>, and <code>eess</code>.
        This version uses optics keywords as the baseline filter and provides one-sentence summaries in English, Chinese, and Japanese for each paper.
      </p>
      <div class="stats" id="stats"></div>
    </section>

    <section class="controls">
      <div class="control-grid">
        <div class="field">
          <label for="search">Search</label>
          <input id="search" class="search" type="search" placeholder="Search by title, author, topic, abstract, or arXiv ID">
        </div>
        <div class="field">
          <label>Category</label>
          <div class="chip-row" id="category-filters"></div>
        </div>
        <div class="field">
          <label>Topic</label>
          <div class="chip-row" id="topic-filters"></div>
        </div>
      </div>
      <div class="meta-row">
        <div id="result-count">Loading...</div>
        <div><a href="../index.html">Back to archive</a></div>
      </div>
    </section>

    <section class="paper-grid" id="paper-grid"></section>
    <section class="empty" id="empty-state">No papers matched your current filters.</section>
  </div>

  <script>
    const papers = __PAPERS_JSON__;
    const categoryOrder = __CATEGORY_ORDER__;
    const topicOrder = __TOPIC_ORDER__;
    const state = {
      search: "",
      categories: new Set(categoryOrder),
      topics: new Set(topicOrder),
    };

    const statsEl = document.getElementById("stats");
    const gridEl = document.getElementById("paper-grid");
    const resultCountEl = document.getElementById("result-count");
    const emptyStateEl = document.getElementById("empty-state");
    const searchEl = document.getElementById("search");

    function escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function statCard(label, value) {
      return `<article class="stat"><div class="label">${label}</div><div class="value">${value}</div></article>`;
    }

    function renderStats() {
      const categoryCounts = Object.fromEntries(categoryOrder.map((cat) => [cat, 0]));
      const topicCounts = Object.fromEntries(topicOrder.map((topic) => [topic, 0]));
      papers.forEach((paper) => {
        categoryCounts[paper.category] = (categoryCounts[paper.category] || 0) + 1;
        (paper.topics || []).forEach((topic) => {
          topicCounts[topic] = (topicCounts[topic] || 0) + 1;
        });
      });
      statsEl.innerHTML = [
        statCard("Papers", papers.length),
        ...categoryOrder.map((cat) => statCard(cat, categoryCounts[cat] || 0)),
        ...topicOrder.map((topic) => statCard(topic, topicCounts[topic] || 0)),
      ].join("");
    }

    function renderChips(containerId, values, selectedSet, onToggle) {
      const container = document.getElementById(containerId);
      container.innerHTML = values.map((value) => {
        const active = selectedSet.has(value) ? "active" : "";
        return `<button class="chip ${active}" type="button" data-value="${escapeHtml(value)}">${escapeHtml(value)}</button>`;
      }).join("");
      container.querySelectorAll(".chip").forEach((button) => {
        button.addEventListener("click", () => onToggle(button.dataset.value));
      });
    }

    function toggleFromSet(set, value) {
      if (set.has(value)) {
        if (set.size > 1) set.delete(value);
      } else {
        set.add(value);
      }
    }

    function matches(paper) {
      const authorText = (paper.authors || []).map((author) => author.name).join(" ");
      const summaryText = [paper.summaries?.en, paper.summaries?.zh, paper.summaries?.ja].join(" ");
      const topicText = (paper.topics || []).join(" ");
      const haystack = [
        paper.id,
        paper.category,
        paper.title,
        paper.abstract,
        paper.subjects,
        authorText,
        topicText,
        summaryText,
      ].join(" ").toLowerCase();
      const topicMatch = (paper.topics || []).some((topic) => state.topics.has(topic));
      return state.categories.has(paper.category) && topicMatch && haystack.includes(state.search);
    }

    function renderPapers() {
      const filtered = papers.filter(matches);
      resultCountEl.textContent = `Showing ${filtered.length} of ${papers.length} papers`;
      emptyStateEl.style.display = filtered.length ? "none" : "block";
      gridEl.innerHTML = filtered.map((paper) => {
        const safeUrl = escapeHtml(paper.url);
        const authors = (paper.featured_authors || []).map((author) => author.name).join(", ") || "Unknown";
        const topics = (paper.topics || []).map((topic) => `<span class="tag topic">${escapeHtml(topic)}</span>`).join("");
        const subjectHtml = paper.subjects
          ? `<div class="subtle"><div class="label">Subjects</div><p class="subject-line">${escapeHtml(paper.subjects)}</p></div>`
          : "";
        return `
        <article class="paper">
          <div class="paper-top">
            <span class="tag category">${escapeHtml(paper.category)}</span>
            ${topics}
          </div>
          <div class="id">arXiv:${escapeHtml(paper.id)}</div>
          <h2><a href="${safeUrl}" target="_blank" rel="noreferrer">${escapeHtml(paper.title)}</a></h2>
          <div class="subtle">
            <div class="label">Authors</div>
            <p class="author-line">${escapeHtml(authors)}</p>
          </div>
          ${subjectHtml}
          <div class="summary-grid">
            <section class="summary-item">
              <strong>English Summary</strong>
              <p>${escapeHtml(paper.summaries?.en || "")}</p>
            </section>
            <section class="summary-item">
              <strong>Chinese Summary</strong>
              <p>${escapeHtml(paper.summaries?.zh || "")}</p>
            </section>
            <section class="summary-item">
              <strong>Japanese Summary</strong>
              <p>${escapeHtml(paper.summaries?.ja || "")}</p>
            </section>
          </div>
          <details>
            <summary>Abstract</summary>
            <p>${escapeHtml(paper.abstract)}</p>
          </details>
          <footer>
            <span>Summary source: ${escapeHtml(paper.summary_source || "fallback")}</span>
            <a href="${safeUrl}" target="_blank" rel="noreferrer">Open on arXiv</a>
          </footer>
        </article>`;
      }).join("");
    }

    function rerenderFilters() {
      renderChips("category-filters", categoryOrder, state.categories, (value) => {
        toggleFromSet(state.categories, value);
        rerenderFilters();
        renderPapers();
      });
      renderChips("topic-filters", topicOrder, state.topics, (value) => {
        toggleFromSet(state.topics, value);
        rerenderFilters();
        renderPapers();
      });
    }

    searchEl.addEventListener("input", (event) => {
      state.search = event.target.value.trim().toLowerCase();
      renderPapers();
    });

    renderStats();
    rerenderFilters();
    renderPapers();
  </script>
</body>
</html>
"""
    return (
        template.replace("__DATE__", date_str)
        .replace("__PAPERS_JSON__", papers_json)
        .replace("__CATEGORY_ORDER__", category_json)
        .replace("__TOPIC_ORDER__", topic_json)
    )


def build_archive_html(entries: list[dict[str, Any]]) -> str:
    items = []
    for entry in entries:
        categories = ", ".join(entry["categories"])
        items.append(
            (
                f'<article class="card">'
                f'<h2><a href="./{entry["date"]}/index.html">{entry["date"]}</a></h2>'
                f'<p>{entry["count"]} papers · categories: {categories}</p>'
                f"</article>"
            )
        )
    cards = "\n".join(items) if items else "<p>No daily pages have been generated yet.</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArXiv Optics Daily Archive</title>
  <style>
    body {{
      margin: 0;
      font-family: "Aptos", "Segoe UI", "Helvetica Neue", sans-serif;
      background: #f4efe7;
      color: #2a221d;
    }}
    .shell {{
      width: min(960px, calc(100% - 32px));
      margin: 0 auto;
      padding: 36px 0 56px;
    }}
    .hero {{
      padding: 28px;
      border-radius: 28px;
      background: rgba(255,255,255,0.88);
      border: 1px solid rgba(42,34,29,0.14);
    }}
    h1 {{ margin: 0 0 8px; font-size: 40px; }}
    p {{ color: #6f5e50; line-height: 1.72; }}
    .grid {{ display: grid; gap: 16px; margin-top: 24px; }}
    .card {{
      padding: 18px 20px;
      border-radius: 22px;
      background: rgba(255,255,255,0.9);
      border: 1px solid rgba(42,34,29,0.12);
    }}
    .card h2 {{ margin: 0 0 10px; font-size: 22px; }}
    a {{ color: #8a3f2d; text-decoration: none; }}
    .button {{
      display: inline-block;
      padding: 10px 14px;
      border-radius: 999px;
      background: #8a3f2d;
      color: white;
      text-decoration: none;
    }}
    .actions {{ margin-top: 18px; display: flex; gap: 12px; }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>ArXiv Optics Daily Archive</h1>
      <p>Open any date below to browse that day's optics-focused report.</p>
      <div class="actions">
        <a class="button" href="./latest.html">Open latest report</a>
      </div>
    </section>
    <section class="grid">{cards}</section>
  </div>
</body>
</html>
"""


def write_archive(output_root: Path) -> None:
    entries: list[dict[str, Any]] = []
    for date_dir in sorted((item for item in output_root.iterdir() if item.is_dir()), reverse=True):
        papers_path = date_dir / "papers.json"
        if not papers_path.exists():
            continue
        papers = json.loads(papers_path.read_text(encoding="utf-8"))
        entries.append(
            {
                "date": date_dir.name,
                "count": len(papers),
                "categories": sorted({paper["category"] for paper in papers}),
            }
        )

    (output_root / "index.html").write_text(build_archive_html(entries), encoding="utf-8")
    if entries:
        latest_target = f"./{entries[0]['date']}/index.html"
        latest_html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={latest_target}">
  <title>Latest ArXiv Optics Daily</title>
</head>
<body>
  <script>window.location.replace("{latest_target}");</script>
  <p><a href="{latest_target}">Open the latest report</a></p>
</body>
</html>
"""
        (output_root / "latest.html").write_text(latest_html, encoding="utf-8")


def resolve_report_date(explicit_date: str | None, timezone_name: str) -> dt.date:
    if explicit_date:
        return dt.date.fromisoformat(explicit_date)
    return dt.datetime.now(ZoneInfo(timezone_name)).date()


def generate(date_str: str | None = None) -> Path:
    config = load_config()
    categories = config.get("categories", [])
    if not categories:
        raise ValueError("No categories configured.")

    timezone_name = config.get("timezone", "America/New_York")
    report_date = resolve_report_date(date_str, timezone_name)
    output_root = ROOT / config.get("output_root", "optics_daily")
    output_root.mkdir(parents=True, exist_ok=True)
    day_dir = output_root / report_date.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    enable_translation = bool(config.get("enable_translation", True))
    max_authors_shown = int(config.get("max_authors_shown", 6))
    deepseek_model = str(config.get("deepseek_model", DEEPSEEK_DEFAULT_MODEL))
    deepseek_client = build_deepseek_client(config)
    deepseek_status = "on" if deepseek_client is not None else "off"

    log(f"[1/5] Preparing optics digest for {report_date.isoformat()}")
    fetched: list[dict[str, Any]] = []
    for index, category in enumerate(categories, start=1):
        url = f"https://arxiv.org/list/{category}/new"
        log(f"[2/5] Fetching category {index}/{len(categories)}: {category}")
        html_text = fetch_text(url)
        category_papers = parse_new_submissions(category, html_text)
        fetched.extend(category_papers)
        log(f"      collected {len(category_papers)} submissions from {category}")

    log(f"[3/5] Filtering {len(fetched)} papers for optics topics")
    log(f"[4/5] Building summaries (DeepSeek={deepseek_status})")
    papers = filter_and_enrich(
        papers=fetched,
        enable_translation=enable_translation,
        max_authors_shown=max_authors_shown,
        deepseek_client=deepseek_client,
        deepseek_model=deepseek_model,
    )
    papers.sort(key=lambda item: (categories.index(item["category"]), item["id"]))
    log(f"      kept {len(papers)} optics-related papers")

    log(f"[5/5] Writing report files into {day_dir}")
    (day_dir / "papers.json").write_text(
        json.dumps(papers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (day_dir / "index.html").write_text(
        build_daily_html(report_date.isoformat(), papers, categories),
        encoding="utf-8",
    )
    write_archive(output_root)
    output_path = day_dir / "index.html"
    log(f"[done] Report ready: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an ArXiv optics daily page.")
    parser.add_argument(
        "--date",
        help="Target report date in YYYY-MM-DD. Defaults to the configured timezone date.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output_path = generate(date_str=args.date)
    except Exception as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
