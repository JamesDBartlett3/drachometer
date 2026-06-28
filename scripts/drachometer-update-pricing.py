#!/usr/bin/env python3
"""Scrape Anthropic's published pricing and refresh drachometer-pricing.json.

Anthropic does not expose a pricing REST API, so this scrapes the public
pricing/model documentation pages. It is intentionally fail-loud: if it cannot
parse valid pricing for every supported tier, it exits non-zero WITHOUT writing
anything, leaving the last-good drachometer-pricing.json in place. The calling workflow
surfaces that failure (notifying maintainers) while the dashboard keeps using
the previously committed prices.

Usage:
    python scripts/drachometer-update-pricing.py            # write repo-root drachometer-pricing.json
    python scripts/drachometer-update-pricing.py --check     # parse + print, do not write
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

PRICING_PATH = Path(__file__).resolve().parent.parent / "drachometer-pricing.json"

# Tiers the dashboard understands. Each logged model is classified into one of
# these by substring match, so we only need a representative price per tier.
# Every tier is OPTIONAL: a tier present on the page is scraped; a tier that is
# absent (e.g. a model withdrawn from sale) keeps its existing drachometer-pricing.json
# value rather than being wiped. The run only fails when NO tier at all can be
# parsed -- that signals the scraper or page format broke, not a model removal.
KNOWN_TIERS = ("fable", "opus", "sonnet", "haiku")

# Documentation pages that publish per-model token pricing.
SOURCE_URLS = {
    "pricing": "https://docs.claude.com/en/docs/about-claude/pricing.md",
    "platform_pricing": "https://platform.claude.com/docs/en/pricing.md",
    "models_overview": "https://platform.claude.com/docs/en/about-claude/models/overview.md",
}

USER_AGENT = "drachometer pricing updater (+https://github.com/JamesDBartlett3/drachometer)"

# Standard Anthropic prompt-caching multipliers relative to base input price.
CACHE_READ_MULT = 0.10
CACHE_CREATE_MULT = 1.25

DOLLAR_RE = re.compile(r"\$\s*([0-9]+(?:\.[0-9]+)?)")


def normalize_cell_text(value: str) -> str:
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    text = re.sub(r"\s*\([^)]*\)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_model_title(value: str) -> str:
    return normalize_cell_text(value).lower()


def parse_table_cells(line: str) -> list[str]:
    return [normalize_cell_text(cell) for cell in line.strip().strip("|").split("|")]


def is_separator_row(cells: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells if cell)


def fetch(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/markdown, text/plain, */*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        print(f"  Could not fetch {url}: {exc}")
        return None


def version_of(text: str, tier: str) -> float:
    """Extract a comparable version number that appears after the tier name.

    'Claude Opus 4.8' -> 4.8 ; 'Sonnet 4' -> 4.0 ; no version -> 0.0
    """
    m = re.search(tier + r"[^\d\n]*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    return float(m.group(1)) if m else 0.0


def parse_tier_pricing(content: str) -> dict:
    """Return {tier: {"input": x, "output": y, "version": v, "title": t}} for tiers found.

    Targets only the *standard* per-model pricing table. Its rows carry the base
    input price, the cache-write/cache-read columns, and the output price -- i.e.
    four or more dollar amounts. The batch-API, long-context-premium, and prose
    rows on the same page each carry only two dollar amounts, so requiring >= 4
    amounts cleanly isolates the standard table without hard-coding its exact
    column count. Within a qualifying row, input is the first amount and output
    is the last; cache prices are derived from input (see build_pricing).

    Deprecated/retired models are skipped, and when several models share a tier
    the highest version number wins so the tier tracks the current model.
    """
    found: dict[str, dict] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("|"):  # only markdown table rows
            continue
        if re.search(r"deprecat|retir", line, re.IGNORECASE):  # skip old models
            continue
        cells = parse_table_cells(line)
        if not cells or is_separator_row(cells):
            continue
        amounts = [float(a) for a in DOLLAR_RE.findall(line)]
        if len(amounts) < 4:  # standard table rows have input + cache cols + output
            continue
        inp, out = amounts[0], amounts[-1]
        if not (0 < inp <= out):  # input should be positive and <= output
            continue
        for tier in KNOWN_TIERS:
            if re.search(r"\b" + tier + r"\b", line, re.IGNORECASE) is None:
                continue
            version = version_of(line, tier)
            prev = found.get(tier)
            if prev is None or version >= prev["version"]:
                found[tier] = {"input": inp, "output": out, "version": version, "title": cells[0]}
            break  # one tier per row
    return found


def parse_model_ids(content: str) -> dict:
    """Return {tier: {"model": api_id, "version": v}} from the models overview tables."""
    found: dict[str, dict] = {}
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("|"):
            i += 1
            continue

        block: list[list[str]] = []
        while i < len(lines) and lines[i].strip().startswith("|"):
            cells = parse_table_cells(lines[i].strip())
            if cells and not is_separator_row(cells):
                block.append(cells)
            i += 1

        if len(block) < 2:
            continue

        header = block[0]
        api_row = next((row for row in block[1:] if row and re.search(r"Claude API ID", row[0], re.IGNORECASE)), None)
        if api_row is None:
            continue

        for title, model_id in zip(header[1:], api_row[1:]):
            if not title or not model_id:
                continue
            for tier in KNOWN_TIERS:
                if re.search(r"\b" + tier + r"\b", title, re.IGNORECASE) is None:
                    continue
                version = version_of(title, tier)
                prev = found.get(tier)
                if prev is None or version >= prev["version"]:
                    found[tier] = {"model": model_id.strip("`"), "version": version}
                break
    return found


def round_price(value: float) -> float:
    # Keep up to 4 decimals but drop trailing-zero noise (0.08, 1.5, 18.75).
    return round(value, 4)


def build_pricing(found: dict, existing_tiers: dict, model_ids: dict) -> dict:
    # Preserve existing tier order, then append any newly-discovered tiers.
    keys = list(existing_tiers.keys())
    for tier in found:
        if tier not in keys:
            keys.append(tier)
    tiers = {}
    for tier in keys:
        existing_tier = existing_tiers.get(tier, {}) if isinstance(existing_tiers.get(tier, {}), dict) else {}
        tier_entry = dict(existing_tier)
        if tier in found:
            inp = round_price(found[tier]["input"])
            tier_entry.update({
                "input": inp,
                "output": round_price(found[tier]["output"]),
                "cache_read": round_price(inp * CACHE_READ_MULT),
                "cache_create": round_price(inp * CACHE_CREATE_MULT),
            })
            if tier in model_ids and model_ids[tier].get("model"):
                tier_entry["model"] = model_ids[tier]["model"]
            tiers[tier] = tier_entry
        elif tier in existing_tiers:
            # Optional tier not on the page right now (e.g. a withdrawn model):
            # carry the existing value forward instead of dropping it.
            tiers[tier] = tier_entry
    return tiers


def load_existing() -> dict:
    try:
        return json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh drachometer-pricing.json from Anthropic's published pricing.")
    parser.add_argument("--check", action="store_true", help="Parse and print without writing drachometer-pricing.json.")
    args = parser.parse_args()

    found: dict = {}
    used_url = None
    for url in SOURCE_URLS.values():
        print(f"Fetching {url} ...")
        content = fetch(url)
        if not content:
            continue
        parsed = parse_tier_pricing(content)
        # Merge so a later page can fill a tier an earlier page missed.
        for tier, data in parsed.items():
            if tier not in found:
                found[tier] = data
        if parsed and used_url is None:
            used_url = url
        if all(tier in found for tier in KNOWN_TIERS):
            break

    if not found:
        print("ERROR: could not parse pricing for any known tier.")
        print("Anthropic's pricing page format may have changed. drachometer-pricing.json left unchanged.")
        return 1

    model_overview = fetch(SOURCE_URLS["models_overview"])
    model_ids = parse_model_ids(model_overview) if model_overview else {}
    if not model_ids:
        print("ERROR: could not parse model ids for any known tier.")
        print("Anthropic's models overview page format may have changed. drachometer-pricing.json left unchanged.")
        return 1
    for tier in found:
        if tier not in model_ids:
            print(f"ERROR: missing model id for tier '{tier}'. drachometer-pricing.json left unchanged.")
            return 1

    existing = load_existing()
    existing_tiers = existing.get("tiers", {}) if isinstance(existing.get("tiers"), dict) else {}
    tiers = build_pricing(found, existing_tiers, model_ids)
    for tier, p in tiers.items():
        note = "" if tier in found else "  (preserved; not on pricing page)"
        print(f"  {tier:6s} input=${p['input']}/MTok output=${p['output']}/MTok "
              f"cache_read=${p['cache_read']} cache_create=${p['cache_create']}{note}")

    document = {
        "_comment": existing.get(
            "_comment",
            "Per-tier token pricing in USD per 1,000,000 tokens. Refreshed automatically "
            "by .github/workflows/update-pricing.yml.",
        ),
        "source": used_url or existing.get("source", SOURCE_URLS["pricing"]),
        "updated": date.today().isoformat(),
        "tiers": tiers,
    }

    if args.check:
        print("\n--check: parsed successfully, not writing.")
        print(json.dumps(document, indent=2))
        return 0

    PRICING_PATH.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {PRICING_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
