---
name: company-lead-discovery
description: Find companies by product and sector, then read their official websites and return a short Turkish shortlist. Use when the user wants OpenClaw to directly search companies on the public web without LinkedIn, browser automation, or private sources.
metadata:
  {
    "openclaw":
      {
        "os": ["linux"],
      },
  }
---

# Company Lead Discovery

Use this skill when the user wants OpenClaw to directly search for companies by product and sector and return a short researched shortlist.

This skill chains:

- public company search
- official website read
- short Turkish summary generation from public evidence

## Safety rules

- Never use LinkedIn.
- Never use browser automation.
- Never use cookies, accounts, or logins.
- Stay on public web sources only.
- Prefer official company websites.
- Do not invent decision makers, emails, or private details.

## Command

Run the workspace script:

```bash
node /home/node/.openclaw/workspace/skills/company-lead-discovery/scripts/company_lead_discovery.mjs --keyword "<urun-veya-anahtar-kelime>" --sector "<sektor>" --limit 5
```

## Output handling

The script returns JSON with:

- `queries`
- `total_candidates`
- `companies`

Each company includes:

- company name
- official website
- short Turkish summary
- short relevance reason
- what is still unknown

When replying to the user:

- write in Turkish
- keep it short and sales-oriented
- list the strongest companies first
- mention public-evidence limits when needed

## Preferred flow

1. Run the script with product and sector.
2. Read the shortlist JSON.
3. Give the user a short Turkish company list.
4. If the user wants one company deeper, continue with a dedicated website-read step.
