#!/usr/bin/env node

const BLOCKED_HOST_TOKENS = [
  "linkedin.com",
  "facebook.com",
  "instagram.com",
  "x.com",
  "twitter.com",
  "youtube.com",
  "tiktok.com",
  "wikipedia.org",
  "amazon.",
  "hepsiburada.",
  "trendyol.",
  "n11.",
  "alibaba.",
  "aliexpress.",
];

const INDUSTRY_TOKENS = [
  "valve",
  "vana",
  "flow",
  "industry",
  "industrial",
  "metal",
  "manufacturing",
  "supplier",
  "manufacturer",
];

const TURKEY_TOKENS = [
  "turkey",
  "turkiye",
  "istanbul",
  "ankara",
  "izmir",
  "bursa",
  "konya",
  "gaziantep",
  "ostim",
];

function foldText(value) {
  return String(value || "")
    .replace(/[ıİ]/g, "i")
    .replace(/[şŞ]/g, "s")
    .replace(/[ğĞ]/g, "g")
    .replace(/[üÜ]/g, "u")
    .replace(/[öÖ]/g, "o")
    .replace(/[çÇ]/g, "c")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function parseArgs(argv) {
  const args = { keyword: "", sector: "", limit: 5 };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];
    if ((token === "--keyword" || token === "--product") && next) {
      args.keyword = next;
      index += 1;
      continue;
    }
    if (token === "--sector" && next) {
      args.sector = next;
      index += 1;
      continue;
    }
    if (token === "--limit" && next) {
      const parsed = Number.parseInt(next, 10);
      if (Number.isFinite(parsed) && parsed > 0) {
        args.limit = Math.min(parsed, 10);
      }
      index += 1;
      continue;
    }
  }
  return args;
}

function buildQueries(keyword, sector) {
  const parts = [keyword, sector].map((item) => (item || "").trim()).filter(Boolean);
  const base = parts.join(" ").trim();
  if (!base) {
    throw new Error("Anahtar kelime veya sektor gerekli.");
  }
  return [
    `${base} manufacturer company Turkey`,
    `${base} industrial supplier official website`,
    `${base} site:.com.tr`,
  ];
}

function decodeHtml(value) {
  return (value || "")
    .replace(/&#x27;/gi, "'")
    .replace(/&#39;/gi, "'")
    .replace(/&quot;/gi, '"')
    .replace(/&amp;/gi, "&")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function canonicalDomain(url) {
  const parsed = new URL(url);
  return parsed.hostname.replace(/^www\./, "").toLowerCase();
}

function rootWebsite(url) {
  const parsed = new URL(url);
  return `${parsed.protocol}//${parsed.host}`;
}

function resolveDuckLink(rawUrl) {
  if (!rawUrl) {
    return null;
  }
  let normalized = rawUrl.trim();
  if (normalized.startsWith("//")) {
    normalized = `https:${normalized}`;
  }
  const parsed = new URL(normalized, "https://duckduckgo.com");
  if (parsed.hostname.includes("duckduckgo.com")) {
    const target = parsed.searchParams.get("uddg");
    if (!target) {
      return null;
    }
    normalized = decodeURIComponent(target);
  }
  if (!/^https?:\/\//i.test(normalized)) {
    return null;
  }
  return normalized;
}

function isAllowedCandidate(url) {
  const host = canonicalDomain(url);
  return !BLOCKED_HOST_TOKENS.some((token) => host.includes(token));
}

function normalizeCompanyTokens(companyName) {
  const ignored = new Set([
    "sanayi",
    "ve",
    "ticaret",
    "ltd",
    "sti",
    "a",
    "s",
    "anonim",
    "sirketi",
    "limited",
  ]);
  const tokens = (foldText(companyName).match(/[a-z0-9]+/g) || []).filter(
    (token) => token.length > 1 && !ignored.has(token),
  );
  return tokens.length ? tokens : [foldText(companyName)];
}

function scoreCandidateDomain(url, companyTokens) {
  const host = canonicalDomain(url);
  let score = 0;
  for (const token of companyTokens) {
    if (host.includes(token)) {
      score += 4;
    }
  }
  if (host.endsWith(".com")) {
    score += 2;
  }
  if (host.endsWith(".com.tr")) {
    score += 3;
  }
  return score;
}

function inferCompanyName(title, url) {
  const normalizedTitle = decodeHtml(title);
  if (normalizedTitle) {
    const primary = normalizedTitle
      .split(/\s[-|\u2013\u2014]\s/)[0]
      .replace(/\b(official website|homepage|anasayfa)\b/gi, "")
      .trim();
    if (primary.length >= 2) {
      return primary;
    }
  }
  const host = canonicalDomain(url).split(".")[0].replace(/-/g, " ");
  return host
    .split(/\s+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function scoreEntry(entry, keyword, sector, companyName) {
  const haystack = foldText(
    [entry.title, entry.snippet, entry.url, companyName].filter(Boolean).join(" "),
  );
  const normalizedKeyword = foldText(keyword);
  const normalizedSector = foldText(sector);
  const host = canonicalDomain(entry.url);
  let score = 0;

  if (normalizedKeyword && haystack.includes(normalizedKeyword)) {
    score += 5;
  }
  if (normalizedSector && haystack.includes(normalizedSector)) {
    score += 3;
  }
  if (INDUSTRY_TOKENS.some((token) => haystack.includes(token))) {
    score += 2;
  }
  if (["manufacturer", "uretim", "uretici", "sanayi", "industrial", "endustri"].some((token) => haystack.includes(token))) {
    score += 4;
  }
  if (TURKEY_TOKENS.some((token) => haystack.includes(token))) {
    score += 4;
  }
  if (host.endsWith(".com.tr") || host.endsWith(".tr")) {
    score += 5;
  }
  if (!host.endsWith(".tr") && !TURKEY_TOKENS.some((token) => haystack.includes(token))) {
    score -= 3;
  }
  score += scoreCandidateDomain(entry.url, normalizeCompanyTokens(companyName));
  return score;
}

function extractSnippetNearby(html, startIndex) {
  const window = html.slice(startIndex, startIndex + 900);
  const match = window.match(
    /<a[^>]+class="result__snippet"[^>]*>(.*?)<\/a>|<div[^>]+class="result__snippet"[^>]*>(.*?)<\/div>/is,
  );
  return decodeHtml((match && (match[1] || match[2])) || "");
}

async function searchEntries(query, maxResults) {
  const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
  const response = await fetch(url, {
    headers: {
      "user-agent": "OpenClawCompanySearch/0.1 (+safe-read-only)",
      accept: "text/html,application/xhtml+xml",
    },
  });
  if (!response.ok) {
    throw new Error(`Arama istegi basarisiz oldu: ${response.status}`);
  }
  const html = await response.text();
  const linkPattern = /<a[^>]+class="result__a"[^>]+href="(?<href>[^"]+)"[^>]*>(?<title>.*?)<\/a>/gis;
  const results = [];
  const seen = new Set();

  for (const match of html.matchAll(linkPattern)) {
    const resolved = resolveDuckLink(match.groups?.href || "");
    if (!resolved || !isAllowedCandidate(resolved)) {
      continue;
    }
    const domain = canonicalDomain(resolved);
    if (seen.has(domain)) {
      continue;
    }
    seen.add(domain);
    results.push({
      url: resolved,
      title: decodeHtml(match.groups?.title || "") || domain,
      snippet: extractSnippetNearby(html, match.index ?? 0),
    });
    if (results.length >= maxResults) {
      break;
    }
  }

  return results;
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const queries = buildQueries(args.keyword, args.sector);
  const scored = new Map();

  for (const query of queries) {
    const entries = await searchEntries(query, Math.max(args.limit * 4, 8));
    for (const entry of entries) {
      const companyName = inferCompanyName(entry.title, entry.url);
      const candidate = {
        company_name: companyName,
        website: rootWebsite(entry.url),
        title: entry.title,
        snippet: entry.snippet,
        query,
      };
      const score = scoreEntry(entry, args.keyword, args.sector, companyName);
      const key = canonicalDomain(entry.url);
      const previous = scored.get(key);
      if (!previous || score > previous.score) {
        scored.set(key, { score, candidate });
      }
    }
  }

  const candidates = Array.from(scored.values())
    .sort((left, right) => right.score - left.score)
    .slice(0, args.limit)
    .map(({ score, candidate }, index) => ({
      rank: index + 1,
      score,
      ...candidate,
    }));

  const output = {
    keyword: args.keyword,
    sector: args.sector,
    queries,
    candidates,
  };

  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

run().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
