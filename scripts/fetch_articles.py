"""Fetch WeChat (mp.weixin.qq.com) articles to Markdown.

Usage:
    python scripts/fetch_articles.py <urls.txt> --out <output_dir>

`urls.txt` holds one article URL per line (blank lines and lines starting
with `#` are ignored).  One Markdown file is written per URL under
<output_dir>.
"""
import urllib.request
import re
import os
import sys
import json
from html import unescape


def _parse_args(argv):
    if len(argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    urls_path = argv[1]
    out = None
    if "--out" in argv:
        out = argv[argv.index("--out") + 1]
    if out is None:
        print("ERROR: --out <output_dir> is required")
        raise SystemExit(2)
    urls = []
    with open(urls_path, "r", encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    if not urls:
        print("ERROR: no URLs found in %s" % urls_path)
        raise SystemExit(2)
    return urls, out


urls, output_dir = _parse_args(sys.argv)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

os.makedirs(output_dir, exist_ok=True)

results = []

for i, url in enumerate(urls):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        # Extract title
        title_match = re.search(r'var\s+msg_title\s*=\s*[\'"](.+?)[\'"]', html)
        if not title_match:
            title_match = re.search(r'<meta\s+property="og:title"\s+content="(.+?)"', html)
        title = title_match.group(1) if title_match else f"article_{i+1}"
        title = unescape(title).strip()

        # Extract author/account
        author_match = re.search(r'var\s+nickname\s*=\s*[\'"](.+?)[\'"]', html)
        author = author_match.group(1) if author_match else "unknown"
        author = unescape(author).strip()

        # Extract publish date
        date_match = re.search(r'var\s+createTime\s*=\s*[\'"](.+?)[\'"]', html)
        pub_date = date_match.group(1) if date_match else ""

        # Extract content area
        content_match = re.search(r'<div\s+class="rich_media_content[^"]*"[^>]*>(.*?)</div>\s*<script', html, re.DOTALL)
        if not content_match:
            content_match = re.search(r'id="js_content"[^>]*>(.*?)</div>', html, re.DOTALL)

        if content_match:
            content_html = content_match.group(1)
        else:
            content_html = "<p>Content extraction failed</p>"

        # Simple HTML to text conversion
        # Remove script and style
        content_html = re.sub(r'<script[^>]*>.*?</script>', '', content_html, flags=re.DOTALL)
        content_html = re.sub(r'<style[^>]*>.*?</style>', '', content_html, flags=re.DOTALL)
        # Replace br with newline
        content_html = re.sub(r'<br\s*/?>', '\n', content_html)
        # Replace p tags
        content_html = re.sub(r'<p[^>]*>', '\n', content_html)
        content_html = re.sub(r'</p>', '\n', content_html)
        # Replace section tags
        content_html = re.sub(r'</section>', '\n', content_html)
        content_html = re.sub(r'<section[^>]*>', '', content_html)
        # Remove all other HTML tags
        text = re.sub(r'<[^>]+>', '', content_html)
        # Decode HTML entities
        text = unescape(text)
        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.strip()

        # Create filename
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)[:80]
        filename = f"{i+1:02d}_{safe_title}.md"
        filepath = os.path.join(output_dir, filename)

        # Write markdown
        md_content = f"""---
title: "{title}"
author: "{author}"
url: "{url}"
date: "{pub_date}"
---

# {title}

> 公众号: {author}
> 链接: {url}
> 发布时间: {pub_date}

---

{text}
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_content)

        results.append({"index": i+1, "title": title, "author": author, "date": pub_date, "file": filename, "status": "ok"})
        print(f"[{i+1:02d}] OK: {title[:60]} ({len(text)} chars) -> {filename}")

    except Exception as e:
        results.append({"index": i+1, "url": url, "status": f"error: {str(e)}"})
        print(f"[{i+1:02d}] ERROR: {str(e)[:80]}")

print(f"\nDone: {sum(1 for r in results if r['status']=='ok')}/{len(urls)} succeeded")
