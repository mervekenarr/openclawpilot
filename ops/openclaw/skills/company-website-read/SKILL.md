---
name: company-website-read
description: Read a company's public website and extract a short sales-relevant summary from official pages only. Use when the user already has a company website and wants a concise summary, public signals, or what the company appears to do. Do not use for LinkedIn, browser automation, cookies, logins, or private sources.
metadata:
  {
    "openclaw":
      {
        "emoji": "📄",
        "os": ["linux"],
      },
  }
---

# Company Website Read

Use this skill after a company website is already known.

This skill is read-only and limited to the official website.

## Safety rules

- Never use LinkedIn.
- Never use browser automation.
- Never use cookies, accounts, or private logins.
- Stay on the official company domain.
- Do not invent decision makers, emails, or private details.
- Prefer short, sales-relevant summaries.

## Command

Run the workspace script:

```bash
node /home/node/.openclaw/workspace/skills/company-website-read/scripts/company_website_read.mjs --url "<resmi-website>" --company "<firma-adi>"
```

## Output handling

The script returns JSON with:

- `title`
- `meta_description`
- `headings`
- `best_summary`
- `text_excerpt`
- `related_pages`
- `relevance`

When replying to the user:

- write in Turkish
- give a short summary of what the company appears to do
- mention one public signal only if the site clearly supports it
- say what is still unknown
- do not dump the full raw text unless the user asks

## Preferred flow

1. Read the official website with the script.
2. Use `best_summary`, `headings`, and `related_pages` first.
3. Give a short Turkish sales-oriented summary.
4. If the site is weak or unclear, say that the public evidence is limited.
