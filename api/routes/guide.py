from pathlib import Path

import markdown
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

API_GUIDE_PATH = Path(__file__).resolve().parent.parent.parent / "API_GUIDE.md"

PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Developer Guide &middot; Seekly</title>
  <link rel="stylesheet" href="/styles.css" />
  <style>
    .guide {{ max-width: 820px; margin: 0 auto; padding: 24px 20px 64px; line-height: 1.6; }}
    .guide h1, .guide h2, .guide h3 {{ line-height: 1.3; }}
    .guide h1 {{ font-size: 1.8rem; margin-top: 0; }}
    .guide h2 {{ font-size: 1.3rem; margin-top: 2.2em; border-top: 1px solid var(--border); padding-top: 0.8em; }}
    .guide h3 {{ font-size: 1.05rem; }}
    .guide p, .guide li {{ color: var(--text-dim); }}
    .guide code {{ background: var(--surface-2); border-radius: 4px; padding: 0.15em 0.4em; font-size: 0.9em; }}
    .guide pre {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; overflow-x: auto; }}
    .guide pre code {{ background: none; padding: 0; }}
    .guide table {{ margin: 1em 0; }}
    .guide a {{ text-decoration: none; }}
    .guide a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="topbar">
      <a class="brand" href="/">Seekly</a>
      <a class="btn btn-ghost" href="/docs">API reference</a>
    </div>
    <div class="guide">
{content}
    </div>
    <footer>Seekly dashboard &middot; AGPL-3.0</footer>
  </div>
</body>
</html>
"""


@router.get("/guide", response_class=HTMLResponse)
async def guide() -> str:
    # Narrative developer guide, distinct from the auto-generated /docs.
    source = API_GUIDE_PATH.read_text(encoding="utf-8")
    content = markdown.markdown(source, extensions=["tables", "fenced_code"])
    return PAGE_TEMPLATE.format(content=content)
