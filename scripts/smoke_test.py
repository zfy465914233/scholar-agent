"""Smoke test: verify SearXNG search + Crawl4AI fetch are operational."""
import asyncio
import json
import sys
import urllib.request
import urllib.error


def test_searxng() -> list[dict]:
    query = "open source optimization solver"
    url = f"http://localhost:8080/search?q={query.replace(' ', '+')}&format=json"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
    except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
        print(f"FAIL: SearXNG unreachable ({e}). Is the container running?")
        sys.exit(1)

    results = data.get("results", [])
    assert len(results) > 0, "SearXNG returned 0 results"
    print(f"SearXNG OK: {len(results)} results for '{query}'")
    for i, r in enumerate(results[:3]):
        print(f"  [{i+1}] {r['title'][:60]}  ->  {r['url'][:80]}")
    return results


async def test_crawl(target_url: str) -> None:
    from crawl4ai import AsyncWebCrawler

    print(f"\nCrawling: {target_url}")
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=target_url)
        md = result.markdown.raw_markdown
        assert len(md) > 0, "Crawl4AI returned empty markdown"
        print(f"Crawl4AI OK: status={result.status_code}, {len(md)} chars")
        print(f"Preview: {md[:200]}...")


if __name__ == "__main__":
    results = test_searxng()
    if results:
        asyncio.run(test_crawl(results[0]["url"]))
    print("\nSmoke test passed.")
