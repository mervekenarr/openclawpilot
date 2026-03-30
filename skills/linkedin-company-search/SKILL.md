---
name: "linkedin-company-search"
description: "Searches for companies on LinkedIn using an authenticated li_at cookie and returns extracted information."
visibility: "public"
permissions:
  - "network"
  - "process"
---

# `linkedin-company-search`

This skill performs a headless search on LinkedIn to discover companies based on a sector and keyword.
It requires the `li_at` authentication cookie to securely fetch results without triggering captchas.

## Architecture

The skill leverages the native Node.js process and `playwright-core` to establish an authenticated connection to LinkedIn.

### Input Parameters

- `--keyword` or `--product`: The specific product, service, or keyword to search for.
- `--sector`: The industry or vertical.
- `--li_at` or `--li_at=`: The persistent session authentication cookie.
- `--limit`: Maximum number of company profiles to extract.

### Under the Hood

1. Initiates a headless Chromium context.
2. Injects the `li_at` cookie into the `.linkedin.com` domain.
3. Constructs an authenticated LinkedIn search query for companies.
4. Parses search result elements and extracts Name, Description, and Link.

## Usage Example

```javascript
node build/scripts/linkedin_search.mjs --keyword "software" --sector "technology" --li_at "AQED..." --limit 5
```
