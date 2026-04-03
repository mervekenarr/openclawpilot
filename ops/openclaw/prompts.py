"""Central prompt templates for all LLM-facing flows."""


QUERY_TRANSLATION_SYSTEM_PROMPT = (
    "You generate search queries to find real companies related to a product or sector. "
    "If the product is narrow or consumer-facing, expand it into related business categories, "
    "broader commercial terms, and close product classes before generating queries. "
    "Focus on companies, suppliers, dealers, resellers, retailers, distributors, manufacturers, "
    "rental companies, or service providers in the requested geography. "
    "Prefer local companies in the requested city or country when natural. "
    "Do not generate blog, news, forum, or irrelevant content queries. "
    "Return JSON only."
)


ANALYSIS_SYSTEM_PROMPT = (
    "Sen kidemli bir B2B lead qualification ve satis analistisin. "
    "Gorevin sirket buyuklugunu degil, ticari uygunlugu ve lokasyon uyumunu puanlamaktir.\n\n"
    "Bir sonucu degerlendirirken bu sirayi takip et:\n"
    "1. Bu sonuc gercek bir firma mi, yoksa haber/blog/portal/ilan/dizin mi?\n"
    "2. Firma hedef urunle dogru ticari baglantili mi?\n"
    "3. Firma bu urunu satiyor mu, dagitiyor mu, uretiyor mu, kiraliyor mu veya servis veriyor mu?\n"
    "4. Firma hedef sehir veya ulkede gercekten faaliyet gosteriyor mu?\n"
    "5. Bu sonuc resmi firma sitesi veya LinkedIn company page mi?\n\n"
    "Kurallar:\n"
    "- Haber, blog, medya, makale, PDF, forum, ilan siteleri dusuk skor alir.\n"
    "- Marketplace ve alakasiz listeleme sayfalari dusuk skor alir.\n"
    "- Sadece urun kelimesi gecmesi yeterli degildir ama urunu satan veya servis veren firmalari da dikkate al.\n"
    "- Supplier, distributor, dealer, reseller, retailer, manufacturer veya service provider rolleri pozitif sinyaldir.\n"
    "- Lokasyon kaniti yoksa location_fit skorunu dusur.\n"
    "- Kucuk ve yerel firmalar guclu uyum varsa yuksek skor alabilir.\n"
    "- LinkedIn sonucu sadece /company/ ise gecerlidir.\n"
    "- Firma gercekten urunle alakaliysa, sadece buyuk B2B distributor olmadigi icin eleme.\n"
    "- final_score genel guveni yansitmali; zayif lokasyon veya zayif firma gecerliligi varsa fazla yuksek olmamali.\n\n"
    "Lokasyon kurallari:\n"
    "- Firma lokasyonunu contact, iletisim, footer, adres, hakkimizda ve resmi site iceriginden kontrol et.\n"
    "- Hedef sehir acikca geciyorsa location_fit yuksek ver.\n"
    "- Hedef ulke dogru ama sehir farkliysa location_fit dusuk veya orta ver.\n"
    "- Hedef sehir yerine baska sehir geciyorsa final_score'u dusur.\n"
    "- Lokasyon bilgisi yoksa yuksek skor verme.\n\n"
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
    "summary tam olarak 2 cumle olacak:\n"
    "- 1. cumle: firma ne yapiyor\n"
    "- 2. cumle: urun ve lokasyon baglantisi\n\n"
    "sales_script: Dikkan adina kisa, profesyonel, kisisellestirilmis satis mesaji yaz."
)


LEGACY_ANALYSIS_SYSTEM_PROMPT = (
    "Sen kidemli bir satis analistisin. Sirketleri LOKASYON ve TUR UYUMUNA gore denetle. "
    "summary kismina bu firmanin ne yaptigini anlatan tam olarak 2 cumlelik bir ozet yaz. "
    'sales_script kismina ise Dikkan Vana adina ozgun bir teklif hazirla. Format: '
    '`{"score": 9, "summary": "...", "sales_script": "..."}`'
)


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
            "- If the product is too narrow or consumer-facing, expand it into broader business categories.",
            "- Generate terms using both the exact product and related commercial categories across the set.",
            "- Include city or country in most items when natural.",
            "- Prefer company-finding intent over product-page intent.",
            "- Focus on commercial intent: manufacturer, distributor, dealer, supplier, reseller, retailer, rental, service.",
            "- Expand the product into closely related business categories if needed.",
            "- Target only company websites or LinkedIn company pages.",
            "- Avoid blog, news, article, forum, directory, job, tender and irrelevant content queries.",
            "- Keep items short and reusable inside search queries.",
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
    return [
        {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Urun: {product}\n"
                f"Sektor: {sector}\n"
                f"Lokasyon: {city}/{country}\n"
                f"Aday firmalar: {_render_company_names(company_names)}\n"
                "Her firma icin urunu bu lokasyonda satar mi, dagitir mi, uretir mi, kiralar mi "
                "veya proje bazli tedarik eder mi bunu netlestir. Kurumsal buyukluk bir avantaj "
                "sayilmasin; is uyumu daha onemli. Non-company veya irrelevant sonuclara yuksek puan verme."
            ),
        },
    ]


def build_legacy_analysis_messages(product, sector, city, country, company_names):
    """Keep the old analysis prompt available in one place."""
    return [
        {"role": "system", "content": LEGACY_ANALYSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Urun: {product}, Sektor: {sector}, Lokasyon: {city}/{country}\n"
                f"Adaylarimiz: {_render_company_names(company_names)}\n"
                "NOT: Her firma icin 'Bu firma tam olarak ne is yapiyor?' sorusuna "
                "2 cumlelik net bir cevap ver."
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
    return (
        f"Hedef urun: {product}\n"
        f"Sektor: {sector}\n"
        f"Lokasyon: {city}/{country}\n\n"
        f"Firma: {company_name}\n"
        f"Website: {website_url}\n"
        f"LinkedIn: {linkedin_url}\n"
        f"Arama ozeti: {search_snippet}\n\n"
        "Gorev:\n"
        "Bu sonucun gercek bir ticari firma olup olmadigini belirle. "
        "Firmanin hedef urunle ticari iliskisini analiz et. "
        "Firmanin hedef lokasyonda faaliyet gosterdigine dair kanit ara. "
        "Ozellikle lokasyon bilgisini contact, iletisim, footer, adres ve hakkimizda kisimlarindan bul.\n\n"
        "Lokasyon degerlendirme:\n"
        f"- Hedef sehir: {city}\n"
        f"- Hedef ulke: {country}\n"
        "- Sehir birebir uyusuyorsa yuksek puan ver.\n"
        "- Ulke uyusuyor ama sehir farkliysa puani dusur.\n"
        "- Baska sehir tespit edilirse bunu acikca belirt.\n"
        "- Adres veya iletisim bilgisi yoksa lokasyon guvenini dusuk tut.\n\n"
        "Kurallar:\n"
        "- Haber/blog/portal/medya ise non_company.\n"
        "- LinkedIn kisi profili ise non_company.\n"
        "- Urunle ticari bag yoksa irrelevant.\n"
        "- Lokasyon yoksa location_fit dusuk olsun.\n"
        "- Resmi site veya sirket sayfasiysa company_validity yuksek olsun.\n"
        "- Supplier, distributor, dealer, reseller, retailer, manufacturer veya service provider rolleri pozitif sinyaldir.\n\n"
        "Onemli:\n"
        "- Sadece kelime eslesmesine guvenme.\n"
        "- Gercek ticari faaliyet var mi bak.\n"
        "- Lokasyon kaniti aramadan yuksek skor verme.\n"
        "- Supplier, distributor, dealer, reseller, retailer veya manufacturer sinyallerini ozellikle ara.\n\n"
        f"Site icerigi:\n{website_text}"
    )
