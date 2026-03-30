---
name: company-search
description: Search public company websites by product and sector using a safe read-only web search script. Use when the user asks to find manufacturers, suppliers, or company websites for a product, category, or sector. Do not use for LinkedIn, browser automation, cookies, logins, or private sources.
metadata:
  {
    "openclaw":
      {
        "os": ["linux"],
      },
  }
---

# Company Search

Use this skill when the user wants OpenClaw to search for companies on the public web by product, category, or sector.

This skill is intentionally read-only and public-web-only.

## Safety rules

- Never use LinkedIn.
- Never use browser automation.
- Never use cookies, accounts, or private logins.
- Prefer official company websites.
- Ignore social media, marketplace, and profile pages.
- Treat this as discovery only, not outreach.

## Command

Run the workspace script with the shell/exec tool:

```bash
node /home/node/.openclaw/workspace/skills/company-search/scripts/company_search.mjs --keyword "<urun-veya-anahtar-kelime>" --sector "<sektor>" --limit 5
```

If the user gives only one of them:

- product only: pass it as `--keyword`
- sector only: pass it as `--sector`

If both are given, pass both.

## Output handling

The script returns JSON with:

- `queries`: the public search queries that were used
- `candidates`: the best matching company website candidates

When replying to the user:

- summarize in Turkish
- show the top companies in a short list
- include company name and website
- include a one-line reason only if it is clearly supported by the search result
- do not invent decision makers or emails

## Preferred flow

1. Run the script.
2. Read the JSON.
3. Give the user a short Turkish shortlist.
4. If the user wants deeper research on one company, say that a second website-read step is needed.
