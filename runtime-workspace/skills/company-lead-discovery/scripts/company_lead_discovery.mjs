#!/usr/bin/env node

import { execFile } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";

const execFileAsync = promisify(execFile);

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
        args.limit = Math.min(parsed, 8);
      }
      index += 1;
    }
  }
  if (!args.keyword && !args.sector) {
    throw new Error("Anahtar kelime veya sektor gerekli.");
  }
  return args;
}

function normalizeText(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

function isLikelyNoise(text) {
  const lowered = normalizeText(text).toLowerCase();
  if (!lowered) {
    return true;
  }
  return [
    "cookie",
    "privacy",
    "kvkk",
    "login",
    "sign in",
    "anasayfa",
    "home page",
  ].some((token) => lowered.includes(token));
}

function buildReason(candidate, websiteRead, keyword, sector) {
  const parts = [
    candidate?.title,
    candidate?.snippet,
    websiteRead?.best_summary,
    websiteRead?.meta_description,
    ...(websiteRead?.headings || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();

  const reasons = [];
  if (keyword && parts.includes(keyword.toLowerCase())) {
    reasons.push(`"${keyword}" ile iliskili public icerik bulundu`);
  }
  if (sector && parts.includes(sector.toLowerCase())) {
    reasons.push(`${sector} baglami sitede gorunuyor`);
  }
  if ((websiteRead?.relevance || "low") === "high") {
    reasons.push("resmi sitede firma faaliyet aciklamasi guclu");
  } else if ((websiteRead?.relevance || "low") === "medium") {
    reasons.push("resmi sitede temel faaliyet bilgisi bulundu");
  }
  return reasons.slice(0, 2).join("; ") || "public web aramasinda urun/sektor ile iliskili gorundu";
}

function buildUnknowns(websiteRead) {
  const unknowns = [
    "karar verici kisi",
    "dogrudan iletisim e-postasi",
    "satin alma ekibi bilgisi",
  ];
  if ((websiteRead?.relevance || "low") === "low") {
    unknowns.unshift("resmi sitede faaliyet aciklamasi sinirli");
  }
  return unknowns;
}

function buildSummary(candidate, websiteRead) {
  const summary = normalizeText(websiteRead?.best_summary || websiteRead?.meta_description || candidate?.snippet || "");
  if (!summary || isLikelyNoise(summary)) {
    return "Resmi web sitesinden sinirli bilgi bulundu; daha derin manuel inceleme gerekebilir.";
  }
  return summary.slice(0, 320);
}

async function runScript(scriptPath, args) {
  const { stdout, stderr } = await execFileAsync("node", [scriptPath, ...args], {
    maxBuffer: 1024 * 1024 * 4,
  });
  if (stderr && stderr.trim()) {
    throw new Error(stderr.trim());
  }
  return JSON.parse(stdout);
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const scriptDir = path.dirname(fileURLToPath(import.meta.url));
  const skillsDir = path.resolve(scriptDir, "..", "..");
  const companySearchScript = path.join(skillsDir, "company-search", "scripts", "company_search.mjs");
  const companyWebsiteReadScript = path.join(
    skillsDir,
    "company-website-read",
    "scripts",
    "company_website_read.mjs",
  );

  const searchResults = await runScript(companySearchScript, [
    "--keyword",
    args.keyword,
    "--sector",
    args.sector,
    "--limit",
    String(Math.max(args.limit, 5)),
  ]);

  const companies = [];
  for (const candidate of searchResults.candidates.slice(0, args.limit)) {
    try {
      const websiteRead = await runScript(companyWebsiteReadScript, [
        "--url",
        candidate.website,
        "--company",
        candidate.company_name,
      ]);

      companies.push({
        rank: companies.length + 1,
        company_name: candidate.company_name,
        website: candidate.website,
        summary_tr: buildSummary(candidate, websiteRead),
        why_relevant_tr: buildReason(candidate, websiteRead, args.keyword, args.sector),
        unknowns_tr: buildUnknowns(websiteRead),
        source: {
          search_title: candidate.title,
          search_snippet: candidate.snippet,
          related_pages: (websiteRead.related_pages || []).map((page) => page.url).slice(0, 3),
        },
      });
    } catch {
      companies.push({
        rank: companies.length + 1,
        company_name: candidate.company_name,
        website: candidate.website,
        summary_tr: normalizeText(candidate.snippet) || "Public aramada firma bulundu fakat resmi site ozeti alinmadi.",
        why_relevant_tr: "public aramada urun/sektor ile iliskili gorundu",
        unknowns_tr: ["resmi site ozeti alinmadi", "karar verici kisi", "dogrudan iletisim e-postasi"],
        source: {
          search_title: candidate.title,
          search_snippet: candidate.snippet,
          related_pages: [],
        },
      });
    }
  }

  process.stdout.write(
    `${JSON.stringify(
      {
        keyword: args.keyword,
        sector: args.sector,
        queries: searchResults.queries || [],
        total_candidates: companies.length,
        companies,
      },
      null,
      2,
    )}\n`,
  );
}

run().catch((error) => {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
});
