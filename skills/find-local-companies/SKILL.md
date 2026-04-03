---
name: find-local-companies
description: Use when asked to find real companies for a product or sector in a target city and country. Generate company-finding queries, search and filter results, enrich candidate websites and LinkedIn company pages, validate location evidence strictly, retry with broader business categories when needed, and return scored JSON results without fabricating companies.
---

# Find Local Companies

## Overview

Use this skill to find real companies, not product pages, from:

- `product`
- `sector`
- `city`
- `country`
- `min_results` with default `5`

Return fewer than `min_results` if evidence is insufficient after retries. Never fabricate companies.

## Target Preference

Prefer these company types:

- suppliers
- distributors
- dealers
- resellers
- manufacturers
- service providers
- retailers only when clearly relevant

Reject these by default:

- news, blog, article, forum, press, media, magazine pages
- job or career pages
- PDFs
- directories
- marketplaces
- social media pages except valid LinkedIn company pages

LinkedIn rules:

- Accept only URLs containing `linkedin.com/company/`
- Reject `linkedin.com/in/`
- Reject `linkedin.com/posts/`
- Reject `linkedin.com/jobs/`
- Reject `linkedin.com/feed/`

## Workflow

### 1. Query Generation

- Generate exactly `8` search queries.
- Include `city` or `country` in most queries.
- Use commercial-intent words such as `supplier`, `distributor`, `dealer`, `reseller`, `manufacturer`, and `company`.
- Prefer company-finding intent over product-page intent.
- If the product is narrow or consumer-facing, expand into related business categories before building the query set.

Expansion examples:

- `klavye` -> `computer accessories`, `IT hardware`, `office equipment`

### 2. Search

- Run search using all generated queries.
- Keep the final executed query list for `queries_used`.

### 3. Filtering

Reject any result whose URL contains:

- `/news`
- `/blog`
- `/article`
- `/posts`
- `/press`
- `/media`
- `/magazine`
- `.pdf`
- `/jobs`
- `/careers`
- `/kariyer`
- `linkedin.com/in/`
- `linkedin.com/posts/`
- `linkedin.com/jobs/`
- `linkedin.com/feed/`
- `facebook.com`
- `instagram.com`
- `youtube.com`

Additional filtering rules:

- Do not return product pages as final companies.
- If a product or category page belongs to a real company, normalize to the company root domain and verify the company there.
- Treat content pages, directories, marketplaces, and profile pages as `non_company`.

### 4. Enrichment

For each surviving candidate:

- visit the homepage
- try `/contact`, `/about`, and `/hakkimizda`
- extract:
  - company name
  - website
  - LinkedIn company page
  - address, city, and country
  - business description

### 5. Location Validation

Location validation is strict and is required for high confidence.

Check city and country from:

- contact page
- footer
- address blocks
- about section
- official site content

Scoring expectations:

- exact city match -> high `location_fit`
- only country match -> medium `location_fit`
- different city -> cannot be `strong_match`
- no location evidence -> low `location_fit`

Hard cap rule:

- if a different city is detected, cap `location_fit` at `4`
- if a different city is detected, cap `final_score` at `5`

Do not assume location without evidence.

### 6. Scoring

Score every company on:

- `product_fit` from `0-10`
- `location_fit` from `0-10`
- `company_validity` from `0-10`
- `commercial_fit` from `0-10`

Then compute `final_score`.

Interpretation:

- `company_validity` measures whether this is a real company page
- `commercial_fit` measures whether the company sells, distributes, manufactures, services, or commercially supports the target product or category
- `final_score` must reflect evidence, not optimism

### 7. Decision

Return one of:

- `strong_match`
- `possible_match`
- `weak_match`
- `non_company`
- `irrelevant`

Decision rules:

- exact city + product relevance + real company -> `strong_match`
- wrong city -> cannot be `strong_match`
- content page, directory, marketplace, product page, or profile page -> `non_company`
- unrelated company -> `irrelevant`

### 8. Retry Logic

If results are below `min_results`:

- expand the product into broader business categories
- rerun search
- merge and deduplicate results by normalized company/root domain
- sort by `final_score` descending

Prefer local companies over big generic sites.

### 9. Output

Return JSON only:

```json
{
  "queries_used": [],
  "results": [
    {
      "company_name": "",
      "website_url": "",
      "linkedin_url": "",
      "detected_city": "",
      "detected_country": "",
      "product_fit": 0,
      "location_fit": 0,
      "company_validity": 0,
      "commercial_fit": 0,
      "final_score": 0,
      "decision": "",
      "summary": "",
      "sales_script": ""
    }
  ]
}
```

## OpenClaw Notes

When working in this repository:

- prefer reusing the company-search and filtering logic in `ops/openclaw/engine.py`
- prefer reusing active prompts in `ops/openclaw/prompts.py`
- preserve strict LinkedIn company-page validation
- preserve strict location validation
