"""Web search backends for Mint Scraper: web (DuckDuckGo and other engines via ddgs), Wikipedia and Brave."""
import os

import requests
from ddgs import DDGS

WIKI_HEADERS = {"User-Agent": "MintScraper/1.0 (https://github.com/Vee-industries)"}


def do_search(query, engine="ddg", max_results=5):
    """Return a list of {"title", "link", "snippet"} dicts for `query`."""
    results = []
    if engine == "ddg":
        try:
            for r in DDGS().text(query, region="us-en", safesearch="off", timelimit="y", max_results=max_results):
                results.append({"title": r["title"], "link": r["href"], "snippet": r.get("body", "")})
        except Exception as ex:
            results.append({"title": "Error", "link": "", "snippet": str(ex)})
    elif engine == "wiki":
        try:
            hits = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={"action": "opensearch", "search": query, "limit": 1, "format": "json"},
                headers=WIKI_HEADERS, timeout=10,
            ).json()
            if not hits[1]:
                return [{"title": "Wikipedia", "link": "", "snippet": f"No Wikipedia article found for '{query}'."}]
            summary = requests.get(
                "https://en.wikipedia.org/api/rest_v1/page/summary/" + hits[1][0].replace(" ", "_"),
                headers=WIKI_HEADERS, timeout=10,
            ).json()
            results.append({"title": summary.get("title", hits[1][0]), "link": hits[3][0],
                            "snippet": summary.get("extract", "")})
        except Exception as ex:
            results.append({"title": "Wikipedia Error", "link": "", "snippet": str(ex)})
    elif engine == "brave":
        api_key = os.getenv("BRAVE_API_KEY", "")
        if not api_key:
            return [{"title": "Brave Error", "link": "", "snippet": "Set the BRAVE_API_KEY environment variable to use Brave."}]
        try:
            resp = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={"q": query, "count": max_results},
                timeout=10,
            )
            resp.raise_for_status()
            for r in resp.json().get("web", {}).get("results", []):
                results.append({"title": r["title"], "link": r["url"], "snippet": r.get("description", "")})
        except Exception as ex:
            results.append({"title": "Brave Error", "link": "", "snippet": str(ex)})
    return results
