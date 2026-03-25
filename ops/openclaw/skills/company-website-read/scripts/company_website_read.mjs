#!/usr/bin/env node

const PRIORITY_TOKENS = [
  "about",
  "about-us",
  "company",
  "corporate",
  "kurumsal",
  "hakkimizda",
  "hakkımızda",
];

const NOISE_TOKENS = [
  "contact",
  "media",
  "news",
  "fairs",
  "announcements",
  "certificates",
  "solution partner",
  "my dikkan",
  "en tr",
  "products industries company media contact",
];

function parseArgs(argv) {
  const args = { url: "", company: "" };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];
    if (token === "--url" && next) {
      args.url = next;
      index += 1;
      continue;
    }
    if ((token === "--company" || token === "--name") && next) {
      args.company = next;
      index += 1;
      continue;
    }
  }
  return args;
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

function normalizeUrl(value) {
  let normalized = (value || "").trim();
  if (!normalized) {
    throw new Error("Website adresi gerekli.");
  }
  if (!/^https?:\/\//i.test(normalized)) {
    normalized = `https://${normalized}`;
  }
  const parsed = new URL(normalized);
  if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) {
    throw new Error("Website adresi gecersiz.");
  }
  return normalized;
}

async function fetchHtmlDocument(url) {
  const response = await fetch(url, {
    headers: {
      "user-agent": "OpenClawCompanyWebsiteRead/0.1 (+safe-read-only)",
      accept: "text/html,application/xhtml+xml",
    },
    redirect: "follow",
  });
  if (!response.ok) {
    throw new Error(`Website HTTP hatasi: ${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  const html = await response.text();
  return {
    html,
    finalUrl: response.url || url,
    contentType,
  };
}

function extractTitle(html) {
  const match = html.match(/<title[^>]*>(.*?)<\/title>/is);
  return decodeHtml(match?.[1] || "");
}

function extractMetaDescription(html) {
  const patterns = [
    /<meta[^>]+name=["']description["'][^>]+content=["'](.*?)["']/is,
    /<meta[^>]+content=["'](.*?)["'][^>]+name=["']description["']/is,
  ];
  for (const pattern of patterns) {
    const match = html.match(pattern);
    if (match?.[1]) {
      return decodeHtml(match[1]);
    }
  }
  return "";
}

function extractHeadings(html) {
  const matches = [...html.matchAll(/<h[1-2][^>]*>(.*?)<\/h[1-2]>/gis)];
  return matches
    .slice(0, 4)
    .map((item) => decodeHtml(item[1] || ""))
    .filter(Boolean);
}

function extractTextExcerpt(html, maxLength = 500) {
  const withoutScripts = html.replace(/<script.*?<\/script>/gis, " ");
  const withoutStyles = withoutScripts.replace(/<style.*?<\/style>/gis, " ");
  const text = decodeHtml(withoutStyles);
  return text ? text.slice(0, maxLength) : "";
}

function extractParagraphCandidates(html) {
  const matches = [
    ...html.matchAll(/<p[^>]*>(.*?)<\/p>/gis),
    ...html.matchAll(/<div[^>]+class=["'][^"']*(?:content|text|about|intro|desc)[^"']*["'][^>]*>(.*?)<\/div>/gis),
  ];
  return matches
    .map((item) => decodeHtml(item[1] || ""))
    .map((text) => text.replace(/\s+/g, " ").trim())
    .filter((text) => text.length >= 60)
    .filter((text) => !looksLikeNavigationNoise(text))
    .slice(0, 8);
}

function looksLikeNavigationNoise(text) {
  const lowered = (text || "").toLowerCase();
  if (!lowered) {
    return true;
  }
  const noiseHits = NOISE_TOKENS.reduce((count, token) => count + (lowered.includes(token) ? 1 : 0), 0);
  return noiseHits >= 3;
}

function extractPriorityLinks(html, baseUrl) {
  const matches = [...html.matchAll(/<a[^>]+href=["']([^"']+)["'][^>]*>(.*?)<\/a>/gis)];
  const baseHost = new URL(baseUrl).hostname.toLowerCase();
  const seen = new Set();
  const scored = [];

  for (const match of matches) {
    const rawHref = (match[1] || "").trim();
    const label = decodeHtml(match[2] || "");
    if (!rawHref || rawHref.startsWith("#") || rawHref.startsWith("javascript:") || rawHref.startsWith("mailto:")) {
      continue;
    }
    let absoluteUrl;
    try {
      absoluteUrl = new URL(rawHref, baseUrl).toString();
    } catch {
      continue;
    }
    const parsed = new URL(absoluteUrl);
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.hostname.toLowerCase() !== baseHost) {
      continue;
    }
    const haystack = `${absoluteUrl.toLowerCase()} ${label.toLowerCase()}`;
    let score = 0;
    for (const token of PRIORITY_TOKENS) {
      if (haystack.includes(token)) {
        score += 3;
      }
    }
    if (score <= 0) {
      continue;
    }
    const normalized = absoluteUrl.replace(/\/$/, "");
    if (seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    scored.push({ score, url: normalized });
  }

  return scored.sort((a, b) => b.score - a.score).slice(0, 1).map((item) => item.url);
}

function buildCombinedExcerpt(textExcerpt, relatedPages) {
  const parts = [];
  if (textExcerpt) {
    parts.push(textExcerpt);
  }
  for (const page of relatedPages) {
    if (page.excerpt) {
      parts.push(page.excerpt);
    }
  }
  return parts.join(" ").replace(/\s+/g, " ").trim().slice(0, 700);
}

function isLowSignal(value) {
  const normalized = (value || "").trim().toLowerCase();
  return !normalized || normalized.length < 12 || ["en", "tr", "english", "turkish", "home", "homepage"].includes(normalized);
}

function chooseBestSummary(metaDescription, textExcerpt, title) {
  if (!isLowSignal(metaDescription)) {
    return metaDescription;
  }
  if (!isLowSignal(textExcerpt)) {
    return textExcerpt.slice(0, 320);
  }
  if (!isLowSignal(title)) {
    return title;
  }
  return "";
}

function estimateRelevance(textExcerpt, companyName) {
  if (!textExcerpt) {
    return "low";
  }
  const loweredExcerpt = textExcerpt.toLowerCase();
  const loweredCompany = (companyName || "").toLowerCase();
  if (loweredCompany && loweredExcerpt.includes(loweredCompany)) {
    return "high";
  }
  if (loweredExcerpt.length > 120) {
    return "medium";
  }
  return "low";
}

function scoreSummaryCandidate(text, companyName) {
  const lowered = (text || "").toLowerCase();
  let score = 0;
  if (!lowered) {
    return score;
  }
  if (companyName && lowered.includes(companyName.toLowerCase())) {
    score += 4;
  }
  for (const token of ["manufacturer", "supplier", "industrial", "valve", "vana", "metal", "engineering", "industry", "solution"]) {
    if (lowered.includes(token)) {
      score += 2;
    }
  }
  if (text.length >= 80 && text.length <= 420) {
    score += 2;
  }
  if (looksLikeNavigationNoise(text)) {
    score -= 6;
  }
  return score;
}

function selectBestSummary(companyName, metaDescription, title, homeParagraphs, relatedPages) {
  const candidates = [];

  if (!isLowSignal(metaDescription)) {
    candidates.push({ text: metaDescription, score: scoreSummaryCandidate(metaDescription, companyName) + 4 });
  }

  for (const item of homeParagraphs) {
    candidates.push({ text: item, score: scoreSummaryCandidate(item, companyName) + 2 });
  }

  for (const page of relatedPages) {
    if (page.excerpt) {
      candidates.push({ text: page.excerpt, score: scoreSummaryCandidate(page.excerpt, companyName) + 3 });
    }
  }

  if (!isLowSignal(title)) {
    candidates.push({ text: title, score: scoreSummaryCandidate(title, companyName) });
  }

  candidates.sort((left, right) => right.score - left.score);
  return candidates[0]?.text?.slice(0, 320) || "";
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const normalizedUrl = normalizeUrl(args.url);
  const root = await fetchHtmlDocument(normalizedUrl);
  if (!root.contentType.toLowerCase().includes("html")) {
    throw new Error("Website HTML donmedi.");
  }

  const title = extractTitle(root.html);
  const metaDescription = extractMetaDescription(root.html);
  const headings = extractHeadings(root.html);
  const textExcerpt = extractTextExcerpt(root.html);
  const homeParagraphs = extractParagraphCandidates(root.html);

  const relatedPages = [];
  for (const url of extractPriorityLinks(root.html, root.finalUrl)) {
    try {
      const related = await fetchHtmlDocument(url);
      if (!related.contentType.toLowerCase().includes("html")) {
        continue;
      }
      relatedPages.push({
        url: related.finalUrl,
        title: extractTitle(related.html),
        excerpt: extractTextExcerpt(related.html, 320),
        paragraphs: extractParagraphCandidates(related.html).slice(0, 3),
      });
    } catch {
      // ignore related page fetch failures
    }
  }

  const combinedExcerpt = buildCombinedExcerpt(textExcerpt, relatedPages);
  const bestSummary = selectBestSummary(
    args.company,
    metaDescription,
    title,
    homeParagraphs,
    relatedPages.flatMap((page) => page.paragraphs || []).length
      ? relatedPages.map((page) => ({
          ...page,
          excerpt: (page.paragraphs || [page.excerpt]).find((item) => item && !looksLikeNavigationNoise(item)) || page.excerpt,
        }))
      : relatedPages,
  ) || chooseBestSummary(metaDescription, combinedExcerpt || textExcerpt, title);
  const relevance = estimateRelevance(combinedExcerpt || textExcerpt, args.company);

  const output = {
    company_name: args.company || null,
    requested_url: normalizedUrl,
    final_url: root.finalUrl,
    title,
    meta_description: metaDescription,
    headings,
    text_excerpt: combinedExcerpt || textExcerpt,
    best_summary: bestSummary,
    relevance,
    related_pages: relatedPages,
  };

  process.stdout.write(`${JSON.stringify(output, null, 2)}\n`);
}

run().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
