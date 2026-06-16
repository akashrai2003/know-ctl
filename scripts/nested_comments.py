"""Test comment scraping on a specific LinkedIn post URN."""
from __future__ import annotations
import argparse, asyncio, json, sys
sys.path.insert(0, "/home/akash-ai/Desktop/social-graph")

async def run(urn: str, max_per_post: int | None, headless: bool) -> None:
    from socialgraph.browser.playwright_client import PlaywrightClient
    from socialgraph.config.settings import Settings
    settings = Settings()
    settings.playwright_headless = headless
    effective_max = max_per_post if max_per_post is not None else settings.max_comments

    print(f"\n{'='*60}")
    print(f"  URN      : {urn}")
    print(f"  Max      : {effective_max}  (SG_MAX_COMMENTS={settings.max_comments})")
    print(f"  Headless : {headless}")
    print(f"{'='*60}\n")

    async with PlaywrightClient(settings) as client:
        print("[*] Fetching comments via DOM extraction + Load-more clicks...")
        result = await client.fetch_comments_batch([urn], max_per_post=effective_max)

    comments = result.get(urn, [])
    with open("/tmp/test_comments_result.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"[+] Saved to /tmp/test_comments_result.json\n")
    print(f"[+] {len(comments)} comment(s) fetched\n")

    if not comments:
        print("  [!] No comments returned."); return

    for i, c in enumerate(comments, 1):
        tags = (" [reply]" if c.get("is_reply") else "") + (" [URL]" if c.get("has_external_url") else "")
        print(f"  [{i:02d}]{tags} {c.get('author','?')!r}")
        print(f"       {c.get('text','').replace(chr(10),' ')[:160]}")
        print()

    print(f"[=] {len(comments)} total | {sum(1 for c in comments if c.get('has_external_url'))} with URLs")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--urn", default="urn:li:activity:7441474406016774145")
    p.add_argument("--max", type=int, default=None)
    p.add_argument("--headless", action="store_true", default=False)
    a = p.parse_args()
    asyncio.run(run(a.urn, a.max, a.headless))

if __name__ == "__main__":
    main()
