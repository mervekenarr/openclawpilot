#!/usr/bin/env node

import { chromium } from "playwright-core";

function parseArgs(argv) {
  const args = { keyword: "", sector: "", liAt: "", limit: 5 };
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i];
    const next = argv[i + 1];
    
    // Allow spaces in arguments like --li_at "token"
    if ((token === "--keyword" || token === "--product") && next) {
      args.keyword = next;
      i++;
    } else if (token === "--sector" && next) {
      args.sector = next;
      i++;
    } else if (token === "--li_at" && next) {
      args.liAt = next;
      i++;
    } else if (token === "--limit" && next) {
      const parsed = parseInt(next, 10);
      if (Number.isFinite(parsed) && parsed > 0) {
        args.limit = Math.min(parsed, 10);
      }
      i++;
    } 
    // Accept --li_at=token format
    else if (token.startsWith("--li_at=")) {
      args.liAt = token.split("=")[1] || "";
    }
  }
  return args;
}

async function run() {
  const args = parseArgs(process.argv.slice(2));

  // If liAt comes embedded directly matching regex from an agent call sometimes like {"li_at": "AQE..."}
  // Try to clean it.
  const rawLiAt = args.liAt.replace(/^["']|["']$/g, "").trim();

  if (!rawLiAt) {
    throw new Error("LinkedIn araması için '--li_at' doğrulaması gereklidir.");
  }
  if (!args.keyword && !args.sector) {
    throw new Error("Arama için anahtar kelime veya sektör belirtmelisiniz.");
  }

  const queryParts = [args.keyword, args.sector].filter(Boolean);
  const searchQuery = encodeURIComponent(queryParts.join(" "));
  const searchUrl = `https://www.linkedin.com/search/results/companies/?keywords=${searchQuery}`;

  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    throw new Error(`Playwright baslatilamadi. Lutfen 'playwright-core' ve bagimliliklarinin yuklu oldugundan emin olun. Hata: ${error.message}`);
  }

  const context = await browser.newContext();

  await context.addCookies([
    {
      name: "li_at",
      value: rawLiAt,
      domain: ".linkedin.com",
      path: "/",
      httpOnly: true,
      secure: true,
      sameSite: "None"
    }
  ]);

  const page = await browser.newPage();
  
  try {
    await page.goto(searchUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
    
    // Auth-wall detection
    if (page.url().includes("login") || page.url().includes("authwall")) {
       throw new Error("Gecersiz veya suresi dolmus 'li_at' cerezi! Lutfen tarayicinizdan guncel bir cerez kopyalayip panele yapistirin.");
    }
    
    await page.waitForSelector("div.search-results-container", { timeout: 15000 }).catch(() => {});

    // Scrape result elements
    const results = await page.evaluate((limit) => {
      const list = [];
      const items = document.querySelectorAll('li.reusable-search__result-container');
      
      for (let i = 0; i < items.length && list.length < limit; i++) {
        const item = items[i];
        
        const nameEl = item.querySelector('span.entity-result__title-text a');
        let companyName = nameEl ? nameEl.innerText.trim() : null;
        if (companyName && companyName.includes('View')) {
            companyName = companyName.split('\\n')[0].trim();
        }
        
        let website = nameEl ? nameEl.href : null;
        if (website && website.includes('?')) {
            website = website.split('?')[0];
        }

        const primaryEl = item.querySelector('div.entity-result__primary-subtitle');
        const primarySubtitle = primaryEl ? primaryEl.innerText.trim() : null;

        const summaryEl = item.querySelector('p.entity-result__summary');
        const summary = summaryEl ? summaryEl.innerText.trim() : null;

        if (companyName) {
          list.push({
            company_name: companyName,
            linkedin_url: website,
            website: null,
            title: primarySubtitle,
            snippet: summary
          });
        }
      }
      return list;
    }, args.limit);

    const output = {
      keyword: args.keyword,
      sector: args.sector,
      queries: [searchQuery],
      candidates: results.map((result, idx) => ({
         rank: idx + 1,
         score: 10 - idx,
         ...result
      }))
    };

    process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);

  } finally {
    await context.close();
    await browser.close();
  }
}

run().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
