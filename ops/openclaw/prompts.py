"""Central prompt templates for all LLM-facing flows."""


QUERY_TRANSLATION_SYSTEM_PROMPT = (
    "You generate company-discovery search queries from Turkish user input. "
    "The user may write the product or sector in Turkish, but queries must be generated in the correct search language for the target country. "
    "If country is Turkey, generate primarily Turkish queries (English terms are optional but allowed). "
    "If country is not Turkey, generate primarily English queries and include the local language of the target country when useful. "
    "Do not rely on Turkish search terms for foreign-country searches. "
    "Always reinterpret the product into exact meaning, broader commercial categories, adjacent industry categories, and common supplier/manufacturer language in that market. "
    "Focus on discovering real companies (suppliers, distributors, manufacturers, dealers, resellers, retailers, service providers). "
    "Avoid blogs, news, forums, jobs, articles, directories, and irrelevant informational pages. "
    "Task: Generate 8 company-discovery search queries in the correct language for the target country. "
    "Return JSON only."
)


ANALYSIS_SYSTEM_PROMPT = (
    "You are a company analysis expert.\n\n"
    "Evaluate:\n"
    "1. Is this a real company?\n"
    "2. Is it related to the product?\n"
    "3. Is there a commercial connection with this product; does it sell, distribute, manufacture or provide service?\n"
    "4. Is it in the target location?\n\n"
    "Location rules:\n"
    "- Check the company location from contact, communication, footer, address, about us and official site content.\n"
    "- First check the target country match and give the score accordingly.\n"
    "- If the target country is clearly mentioned, location_fit can be high.\n"
    "- If another country is detected, location_fit should be low.\n"
    "- If city information is available, use it as a helper signal, but the main filter should be country.\n"
    "- Do not give high score if location information is missing.\n\n"
    "Rules:\n"
    "- News, blog, media, article, PDF, forum, advertisement sites get low scores.\n"
    "- Marketplace and irrelevant listing pages get low scores.\n"
    "- Give points if it's a company.\n"
    "- Give points if it's related to the product.\n"
    "- Give points if location is there.\n"
    "- Just the product word appearing is not enough, but also consider companies that sell or service the product.\n"
    "- Supplier, distributor, dealer, reseller, retailer, manufacturer or service provider roles are positive signals.\n"
    "- Reduce location_fit score if no location evidence.\n"
    "- Small and local companies can get high scores if strong fit.\n"
    "- LinkedIn result is only valid if /company/.\n"
    "- If the company is really related to the product, don't eliminate just because it's not a big B2B distributor.\n"
    "- final_score should reflect general confidence; if weak location or weak company validity, don't make it too high.\n"
    "- Don't eliminate the company just because city info is missing or city is different; country match should be more important.\n\n"
    'JSON only:\n'
    '{\n'
    '  "product_fit": 0-10,\n'
    '  "location_fit": 0-10,\n'
    '  "company_validity": 0-10,\n'
    '  "commercial_fit": 0-10,\n'
    '  "final_score": 0-10,\n'
    '  "decision": "strong_match | possible_match | weak_match | non_company | irrelevant",\n'
    '  "company_type": "manufacturer | distributor | dealer | supplier | rental | service | retailer | marketplace | media | directory | unknown",\n'
    '  "summary": "...",\n'
    '  "sales_script": "..."\n'
    '}\n\n'
    "summary will be exactly 2 sentences:\n"
    "- 1st sentence: what the company does\n"
    "- 2nd sentence: product and location connection\n\n"
    "sales_script: Write a short, professional, personalized sales message on behalf of Dikkan."
)


LEGACY_ANALYSIS_SYSTEM_PROMPT = (
    "You are a senior sales analyst. Evaluate companies according to LOCATION and TYPE FIT. "
    "Write a summary of exactly 2 sentences explaining what this company does. "
    'Prepare a unique offer on behalf of Dikkan Vana for the sales_script part. Format: '
    '`{"score": 9, "summary": "...", "sales_script": "..."}`'
)


def _clean_prompt_part(value):
    return str(value or "").strip()


def _format_location(city="", country=""):
    parts = [_clean_prompt_part(city), _clean_prompt_part(country)]
    parts = [part for part in parts if part]
    return " / ".join(parts) if parts else "-"


def _render_company_names(company_names):
    cleaned = [str(name).strip() for name in (company_names or []) if str(name).strip()]
    return ", ".join(cleaned) if cleaned else "-"


def build_query_translation_prompt(phrase, country_label, target_languages, kind_label, city=""):
    """Return the query-translation prompt body used by both generate/chat calls."""
    lines = [
        f'Turkish input: "{phrase}"',
        f"Country: {country_label}",
    ]
    if city:
        lines.append(f"City: {city}")
    lines.extend(
        [
            f"Target language codes: {', '.join(target_languages)}",
            f"Type: {kind_label}",
            "Task: Generate 8 short search queries or query fragments to find real companies.",
            "",
            "Rules:",
            "- Generate exactly 8 queries.",
            "- 2 queries should be exact product queries.",
            "- 2 queries should be broader commercial category queries.",
            "- 2 queries should be business-role queries (supplier/distributor/manufacturer/dealer/reseller/service).",
            "- 2 queries should be general company discovery queries.",
            "- If country is Turkey: produce primarily Turkish queries (include English variants optionally).",
            "- If country is not Turkey: produce primarily English queries and include local-country language queries if useful.",
            "- Reinterpret product into exact meaning, broader category, adjacent industry category, and supplier/manufacturer market terms.",
            "- Focus on real companies, not product pages or informational content.",
            "- Avoid blog, news, forum, job, article, directory, or irrelevant informational pages.",
            "- Include location or country tokens in most queries when appropriate for better local relevance.",
            "- Keep items short, practical, and directly usable for search engines.",
            "- Prefer patterns like 'X supplier city', 'X distributor city', 'X manufacturer country', 'X companies country'.",
            "- No explanations.",
            "",
            'Return JSON only: {"terms":["term 1","term 2"]}',
        ]
    )
    return "\n".join(lines)


def build_query_translation_messages(prompt):
    """Wrap the query-translation prompt in chat messages."""
    return [
        {"role": "system", "content": QUERY_TRANSLATION_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]


def build_analysis_base_messages(product, sector, city, country, company_names):
    """Return the primary analysis prompt bundle used for company scoring."""
    location_label = _format_location(city, country)
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Product: {product}\n"
                f"Sector: {sector}\n"
                f"Location: {location_label}\n"
                f"Candidate companies: {_render_company_names(company_names)}\n"
                "For each company, clarify if they sell, distribute, manufacture, rent the product in this location "
                "or provide project-based supply. Corporate size should not be an advantage; business fit is more important. "
                "Do not give high scores to non-company or irrelevant results."
            ),
        },
    ]


def build_legacy_analysis_messages(product, sector, city, country, company_names):
    """Keep the old analysis prompt available in one place."""
    location_label = _format_location(city, country)
    return [
        {"role": "system", "content": LEGACY_ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Product: {product}, Sector: {sector}, Location: {location_label}\n"
                f"Our candidates: {_render_company_names(company_names)}\n"
                "NOTE: For each company, give a clear 2-sentence answer to the question 'What exactly does this company do?'"
            ),
        },
    ]


def build_company_analysis_prompt(
    company_name,
    website_url,
    linkedin_url,
    search_snippet,
    website_text,
    product,
    sector,
    city,
    country,
):
    """Return the company-specific analysis prompt body."""
    location_label = _format_location(city, country)
    location_rules = [
        "Location evaluation:",
        f"- Target country: {country}",
        "- If matches target country, location_fit can be high.",
        "- If another country is detected, location_fit should be low.",
        "- If no address or contact info, keep location confidence low.",
    ]
    if _clean_prompt_part(city):
        location_rules.extend(
            [
                f"- Target city: {city}",
                "- If city matches exactly, give extra confidence.",
                "- If country matches but city different, reduce score.",
                "- If another city detected, specify clearly.",
                "- If detected city differs from target city, location_fit max 4, final_score max 5.",
            ]
        )
    return (
        f"Target product: {product}\n"
        f"Sector: {sector}\n"
        f"Location: {location_label}\n\n"
        f"Company: {company_name}\n"
        f"Website: {website_url}\n"
        f"LinkedIn: {linkedin_url}\n"
        f"Search snippet: {search_snippet}\n\n"
        "Task:\n"
        "Determine if this result is a real commercial company. "
        "Analyze the company's commercial relationship with the target product. "
        "Look for evidence that the company operates in the target location. "
        "Especially find location information from contact, communication, footer, address and about us sections.\n\n"
        + "\n".join(location_rules) + "\n\n"
        "Rules:\n"
        "- If news/blog/portal/media, then non_company.\n"
        "- If LinkedIn personal profile, then non_company.\n"
        "- If no commercial connection with product, irrelevant.\n"
        "- If no location, location_fit should be low.\n"
        "- If official site or company page, company_validity should be high.\n"
        "- Supplier, distributor, dealer, reseller, retailer, manufacturer or service provider roles are positive signals.\n\n"
        "Important:\n"
        "- Do not rely only on word matching.\n"
        "- Check if there is real commercial activity.\n"
        "- Do not give high score without location evidence.\n"
        "- Especially look for supplier, distributor, dealer, reseller, retailer or manufacturer signals.\n\n"
        f"Site content:\n{website_text}"
    )
