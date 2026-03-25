import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException

from app import sqlite_store, store
from app.adapters.openclaw_client import (
    create_enrichment_draft,
    get_ollama_probe,
    get_runtime_info,
    plan_company_search,
    plan_research_tools,
    select_company_candidates,
)
from app.research_policy import get_research_policy
from app.api.ai_routes import (
    approve_ai_draft,
    archive_ai_draft,
    compare_ai_drafts,
    create_raw_lead_enrichment_draft,
    get_ai_draft_preview,
    get_raw_lead_openclaw_preview,
    get_raw_lead_drafts,
    reject_ai_draft,
    restore_ai_draft,
)
from app.api.crawl_routes import (
    create_raw_lead_note,
    get_raw_lead_timeline,
    list_raw_leads,
    patch_raw_lead,
    review_lead,
)
from app.api.lead_routes import (
    approve_first_message,
    create_lead_note,
    crm_sync,
    draft_first_message,
    draft_follow_up,
    get_lead_timeline,
    list_leads,
    patch_lead,
    save_reply,
    send_first_message,
)
from app.services.ai_service import build_safe_enrichment_request
from app.schemas.ai import AIDraftReviewRequest
from app.schemas.leads import (
    CRMUpdateRequest,
    LeadReviewRequest,
    LeadUpdateRequest,
    MessageDraftRequest,
    NoteCreateRequest,
    RawLeadUpdateRequest,
    ReplyUpdateRequest,
)
from app.services.openclaw_service import create_manual_raw_lead, discover_raw_leads, enrich_lead, generate_raw_leads

REVIEWER_ROLE = "reviewer"
SALES_ROLE = "sales"


class BackendWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.original_database_url = os.environ.pop("DATABASE_URL", None)
        self.original_backend = store._backend
        self.original_database_url_cache = store._database_url
        self.original_data_dir = sqlite_store.DATA_DIR
        self.original_db_path = sqlite_store.DB_PATH
        self.original_initialized = sqlite_store._initialized

        self.temp_dir_path = self.original_data_dir
        self.temp_db_path = self.temp_dir_path / f"test_openclaw_pilot_{uuid4().hex}.db"

        sqlite_store.DATA_DIR = self.temp_dir_path
        sqlite_store.DB_PATH = self.temp_db_path
        sqlite_store._initialized = False
        store._backend = None
        store._database_url = None
        store.init_db()

    def tearDown(self):
        if self.original_database_url is not None:
            os.environ["DATABASE_URL"] = self.original_database_url

        sqlite_store.DATA_DIR = self.original_data_dir
        sqlite_store.DB_PATH = self.original_db_path
        sqlite_store._initialized = self.original_initialized
        store._backend = self.original_backend
        store._database_url = self.original_database_url_cache
        if self.temp_db_path.exists():
            try:
                self.temp_db_path.unlink()
            except PermissionError:
                pass

    def test_raw_lead_edit_filters_and_timeline(self):
        raw_lead = enrich_lead(generate_raw_leads("timeline-test", "Teknoloji", 1)[0])

        patched_raw_lead = patch_raw_lead(
            raw_lead["id"],
            RawLeadUpdateRequest(
                priority="high",
                summary="Elle guncellenmis raw lead ozeti",
                review_note="Analist kontrol notu",
            ),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        noted_raw_lead = create_raw_lead_note(
            raw_lead["id"],
            NoteCreateRequest(note="Analist notu eklendi"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )

        filtered_raw_leads = list_raw_leads(
            priority="high",
            search="Analist notu eklendi",
            limit=10,
            offset=0,
        )
        raw_timeline = get_raw_lead_timeline(raw_lead["id"])

        self.assertEqual(patched_raw_lead["priority"], "high")
        self.assertTrue(any("Analist notu eklendi" in note for note in noted_raw_lead["personal_notes"]))
        self.assertTrue(any(item["id"] == raw_lead["id"] for item in filtered_raw_leads))
        self.assertTrue(any(entry["type"] == "note" for entry in raw_timeline["entries"]))

    def test_openclaw_runtime_reports_safe_ollama_sandbox(self):
        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "true",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:7b-instruct",
                "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": "qwen2.5:7b-instruct",
                "OPENCLAW_ALLOW_BROWSER_AUTOMATION": "false",
                "OPENCLAW_ALLOW_LIVE_SEND": "false",
            },
            clear=False,
        ):
            runtime = get_runtime_info()

        self.assertEqual(runtime["setup_state"], "ollama_sandbox_ready")
        self.assertEqual(runtime["model_provider"], "ollama")
        self.assertEqual(runtime["model_name"], "qwen2.5:7b-instruct")
        self.assertTrue(runtime["ollama"]["configured"])
        self.assertFalse(runtime["safety"]["browser_automation_enabled"])
        self.assertFalse(runtime["safety"]["live_send_enabled"])
        self.assertFalse(runtime["live_calls_enabled"])

    def test_openclaw_runtime_reports_live_ollama_without_gateway(self):
        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "false",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "http://172.16.41.43:11434",
                "OLLAMA_MODEL": "qwen2.5:14b",
                "OPENCLAW_ALLOW_BROWSER_AUTOMATION": "false",
                "OPENCLAW_ALLOW_LIVE_SEND": "false",
                "OPENCLAW_GATEWAY_URL": "",
                "OPENCLAW_API_KEY": "",
            },
            clear=False,
        ):
            runtime = get_runtime_info()

        self.assertEqual(runtime["setup_state"], "ollama_live_ready")
        self.assertTrue(runtime["ollama"]["configured"])
        self.assertTrue(runtime["can_generate_drafts"])
        self.assertTrue(runtime["live_calls_enabled"])
        self.assertFalse(runtime["gateway_ready"])

    def test_research_policy_blocks_linkedin_and_allows_safe_web_sources(self):
        with patch.dict(
            os.environ,
            {
                "SAFE_WEB_RESEARCH_ENABLED": "true",
                "SAFE_NEWS_SEARCH_ENABLED": "true",
            },
            clear=False,
        ):
            policy = get_research_policy()

        self.assertTrue(policy["real_search_enabled"])
        self.assertTrue(policy["safe_news_enabled"])
        self.assertIn("company_website", policy["allowed_source_ids"])
        self.assertIn("news_scan", policy["allowed_source_ids"])
        self.assertIn("public_registry", policy["allowed_source_ids"])
        self.assertIn("linkedin", policy["blocked_source_ids"])

    def test_safe_web_research_enriches_manual_raw_lead(self):
        raw_lead = create_manual_raw_lead(
            keyword="vana",
            company_name="Gercek Firma",
            website="https://example.com",
            sector="metal",
        )

        with patch.dict(os.environ, {"SAFE_WEB_RESEARCH_ENABLED": "true"}, clear=False):
            with patch(
                "app.services.research_service.fetch_company_website_summary",
                return_value={
                    "source_type": "company_website",
                    "requested_url": "https://example.com",
                    "final_url": "https://example.com",
                    "title": "Gercek Firma | Endustriyel Vana",
                    "meta_description": "Endustriyel vana ve akiskan kontrol cozumleri sunuyor.",
                    "headings": ["Endustriyel vana", "Akiskan kontrol"],
                    "text_excerpt": "Gercek Firma endustriyel vana ve otomasyon alaninda uretim yapar.",
                    "relevance": "high",
                },
            ):
                enriched = enrich_lead(raw_lead)

        self.assertEqual(enriched["research_status"], "completed")
        self.assertEqual(enriched["status"], "needs_review")
        self.assertEqual(enriched["data_reliability"], "high")
        self.assertTrue(any(note.startswith("[public-web]") for note in enriched["personal_notes"]))
        self.assertIn("web sitesi incelendi", enriched["recent_signal"].lower())
        self.assertEqual(enriched["research_bundle"]["mode"], "safe_web_first")
        self.assertEqual(enriched["research_bundle"]["evidence_summary"]["reviewed_count"], 1)
        research_runs = store.list_research_runs(raw_lead_id=raw_lead["id"])
        self.assertEqual(len(research_runs), 1)
        self.assertEqual(research_runs[0]["status"], "completed")
        self.assertEqual(research_runs[0]["mode"], "safe_web_first")

    def test_completed_research_with_bundle_returns_immediately(self):
        raw_lead = create_manual_raw_lead(
            keyword="vana",
            company_name="Gercek Firma",
            website="https://example.com",
            sector="metal",
        )
        raw_lead["research_status"] = "completed"
        raw_lead["status"] = "needs_review"
        raw_lead["research_bundle"] = {"mode": "safe_web_first", "sources": [], "evidence_summary": {}}
        saved = store.save_raw_lead(raw_lead)

        with patch("app.services.openclaw_service.build_research_result") as build_research_result:
            result = enrich_lead(saved)

        build_research_result.assert_not_called()
        self.assertEqual(result["id"], saved["id"])
        research_runs = store.list_research_runs(raw_lead_id=saved["id"])
        self.assertEqual(len(research_runs), 1)
        self.assertEqual(research_runs[0]["status"], "reused")

    def test_keyword_discovery_creates_real_candidate_records(self):
        with patch(
            "app.services.openclaw_service.discover_company_candidates",
            return_value=[
                {
                    "company_name": "Dikkan Valve",
                    "website": "https://www.dikkanvalve.com",
                    "source": "web_discovery",
                    "title": "Dikkan Valve",
                    "snippet": "Endustriyel vana ve akis yonetimi cozumleri.",
                }
            ],
        ):
            records = discover_raw_leads("vana", "metal", 5)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["company_name"], "Dikkan Valve")
        self.assertEqual(records[0]["source"], "web_discovery")
        self.assertTrue(any("guvenli web aramasi" in note.lower() for note in records[0]["personal_notes"]))

    def test_openclaw_guided_discovery_creates_candidate_records(self):
        with patch.dict(
            os.environ,
            {
                "OPENCLAW_AGENT_DISCOVERY_ENABLED": "true",
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "false",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "http://172.16.41.43:11434",
                "OLLAMA_MODEL": "qwen2.5:14b",
            },
            clear=False,
        ):
            with patch(
                "app.services.openclaw_discovery_service.plan_company_search",
                return_value={
                    "provider": "openclaw-ollama-live",
                    "mode": "sandbox",
                    "plan": {
                        "goal": "Vana odakli uretici firmalari bulmak icin sorgular olusturuldu.",
                        "queries": [
                            {
                                "query": "vana metal manufacturer company Turkey",
                                "reason": "Vana ve metal odakli resmi firma sitelerini bulmak icin.",
                            }
                        ],
                    },
                },
            ):
                with patch(
                    "app.services.openclaw_discovery_service.search_company_candidates",
                    return_value=[
                        {
                            "company_name": "Dikkan Valve",
                            "website": "https://www.dikkanvalve.com",
                            "source": "web_search_result",
                            "title": "Dikkan Valve",
                            "snippet": "Endustriyel vana ureticisi.",
                            "query": "vana metal manufacturer company Turkey",
                        }
                    ],
                ):
                    with patch(
                        "app.services.openclaw_discovery_service.select_company_candidates",
                        return_value={
                            "provider": "openclaw-ollama-live",
                            "mode": "sandbox",
                            "selection": {
                                "goal": "En uygun resmi firma adaylari secildi.",
                                "selected_candidates": [
                                    {
                                        "candidate_id": 1,
                                        "reason": "Resmi site ve vana odagi nedeniyle uygun gorunuyor.",
                                        "confidence": "high",
                                    }
                                ],
                            },
                        },
                    ):
                        records = discover_raw_leads("vana", "metal", 5)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["company_name"], "Dikkan Valve")
        self.assertEqual(records[0]["source"], "openclaw_discovery")
        self.assertTrue(any("openclaw" in note.lower() for note in records[0]["personal_notes"]))
        self.assertTrue(any("arama sorgusu" in note.lower() for note in records[0]["personal_notes"]))

    def test_research_bundle_can_include_safe_news_evidence(self):
        raw_lead = create_manual_raw_lead(
            keyword="vana",
            company_name="Gercek Firma",
            website="https://example.com",
            sector="metal",
        )

        with patch.dict(
            os.environ,
            {
                "SAFE_WEB_RESEARCH_ENABLED": "true",
                "SAFE_NEWS_SEARCH_ENABLED": "true",
            },
            clear=False,
        ):
            with patch(
                "app.services.research_service.fetch_company_website_summary",
                return_value={
                    "source_type": "company_website",
                    "requested_url": "https://example.com",
                    "final_url": "https://example.com",
                    "title": "Gercek Firma | Endustriyel Vana",
                    "meta_description": "Endustriyel vana ve akiskan kontrol cozumleri sunuyor.",
                    "headings": ["Endustriyel vana", "Akiskan kontrol"],
                    "text_excerpt": "Gercek Firma endustriyel vana ve otomasyon alaninda uretim yapar.",
                    "best_summary": "Endustriyel vana ve akiskan kontrol cozumleri sunuyor.",
                    "relevance": "high",
                },
            ):
                with patch(
                    "app.services.research_service.search_company_news_signals",
                    return_value=[
                        {
                            "source_type": "news_scan",
                            "url": "https://news.example.com/gercek-firma-yatirim",
                            "title": "Gercek Firma yeni hat yatirimi acikladi",
                            "snippet": "Firma yeni hat yatirimi ve vana uretim kapasitesi hakkinda aciklama yapti.",
                            "published_at": "2026-03-24",
                        }
                    ],
                ):
                    enriched = enrich_lead(raw_lead)

        self.assertEqual(enriched["research_bundle"]["evidence_summary"]["news_count"], 1)
        self.assertEqual(enriched["research_bundle"]["evidence_summary"]["reviewed_count"], 2)
        self.assertTrue(any(item["source_id"] == "news_scan" for item in enriched["research_bundle"]["sources"]))
        self.assertTrue(any(note.startswith("[public-news]") for note in enriched["personal_notes"]))

    def test_safe_enrichment_request_includes_public_web_context(self):
        raw_lead = create_manual_raw_lead(
            keyword="pompa",
            company_name="Ornek Pompa",
            website="https://example.com",
            sector="makine",
        )
        raw_lead["company_summary"] = "Sirketin web sitesinde endustriyel pompa urunleri listeleniyor."
        raw_lead["recent_signal"] = "Company website reviewed: Ornek Pompa"
        raw_lead["fit_reason"] = "Public website content reviewed."
        raw_lead["personal_notes"] = [
            "[public-web] Source URL: https://example.com",
            "[public-web] Page title: Ornek Pompa",
            "[public-news] Title: Ornek Pompa yeni urun lansmani",
            "[internal] analyst note",
        ]
        raw_lead["research_bundle"] = {
            "mode": "safe_web_first",
            "built_at": "2026-03-25T00:00:00Z",
            "inputs": {
                "raw_lead_id": raw_lead["id"],
                "company_name": raw_lead["company_name"],
            },
            "evidence_summary": {
                "source_count": 2,
                "reviewed_count": 2,
                "high_confidence_count": 1,
                "news_count": 1,
            },
            "sources": [
                {
                    "source_id": "company_website",
                    "label": "Sirket web sitesi",
                    "status": "reviewed",
                    "url": "https://example.com",
                    "title": "Ornek Pompa",
                    "snippet": "Endustriyel pompa urunleri listeleniyor.",
                    "confidence": "high",
                    "relevance": "high",
                    "published_at": None,
                },
                {
                    "source_id": "news_scan",
                    "label": "Haber taramasi",
                    "status": "reviewed",
                    "url": "https://news.example.com/ornek-pompa",
                    "title": "Ornek Pompa yeni urun lansmani",
                    "snippet": "Yeni urun duyurusu paylasildi.",
                    "confidence": "medium",
                    "relevance": "medium",
                    "published_at": "2026-03-24",
                },
            ],
        }

        request_payload = build_safe_enrichment_request(raw_lead)

        self.assertEqual(request_payload["company_summary"], raw_lead["company_summary"])
        self.assertEqual(request_payload["recent_signal"], raw_lead["recent_signal"])
        self.assertEqual(request_payload["fit_reason"], raw_lead["fit_reason"])
        self.assertEqual(len(request_payload["public_research_notes"]), 3)
        self.assertEqual(request_payload["research_bundle"]["evidence_summary"]["news_count"], 1)
        self.assertEqual(len(request_payload["research_bundle"]["sources"]), 2)

    def test_manual_raw_lead_can_auto_discover_website(self):
        with patch.dict(os.environ, {"SAFE_SITE_DISCOVERY_ENABLED": "true"}, clear=False):
            with patch(
                "app.services.openclaw_service.discover_company_website",
                return_value="https://ornekfirma.com",
            ):
                raw_lead = create_manual_raw_lead(
                    keyword="vana",
                    company_name="Ornek Firma",
                    website=None,
                    sector="metal",
                )

        self.assertEqual(raw_lead["website"], "https://ornekfirma.com")
        self.assertTrue(any("Website otomatik bulundu" in note for note in raw_lead["personal_notes"]))

    def test_ollama_probe_reports_ready_when_model_exists(self):
        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "true",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:7b-instruct",
                "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
                "OLLAMA_MODEL": "qwen2.5:7b-instruct",
            },
            clear=False,
        ):
            with patch("app.adapters.openclaw_client._fetch_ollama_tags", return_value=["qwen2.5:7b-instruct"]):
                probe = get_ollama_probe()

        self.assertTrue(probe["enabled"])
        self.assertTrue(probe["configured"])
        self.assertTrue(probe["reachable"])
        self.assertTrue(probe["model_installed"])
        self.assertEqual(probe["status"], "ready")

    def test_ollama_live_draft_uses_remote_json_response(self):
        payload = {
            "raw_lead_id": 7,
            "company_name": "Atlas Metal",
            "website": "https://atlas.example",
            "sector": "metal",
            "keyword": "dokum",
            "source": "manual",
            "missing_fields": ["decision_maker_email"],
        }
        ollama_response = {
            "response": """
            {
              "company_summary": "Atlas Metal appears to be a manufacturing-focused company with a likely B2B purchasing workflow.",
              "recent_signal": "Public signal is not yet verified and needs manual validation.",
              "fit_reason": "The company may benefit from operational efficiency and supplier process support.",
              "summary": "A cautious enrichment draft based on limited sanitized input.",
              "priority": "medium",
              "confidence": "low",
              "data_reliability": "low",
              "decision_maker": {
                "name": null,
                "title": null,
                "email": null,
                "linkedin_hint": null
              },
              "missing_fields": ["decision_maker_email", "decision_maker_name"],
              "source_notes": ["Inference is generic because only sanitized input was provided."]
            }
            """
        }

        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "false",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "http://172.16.41.43:11434",
                "OLLAMA_MODEL": "qwen2.5:14b",
                "OLLAMA_TIMEOUT": "300",
            },
            clear=False,
        ):
            with patch("app.adapters.openclaw_client._call_ollama_generate", return_value=ollama_response):
                result = create_enrichment_draft(payload)

        self.assertEqual(result["provider"], "openclaw-ollama-live")
        self.assertEqual(result["draft"]["priority"], "medium")
        self.assertIn("Ollama uzerinden sanitize edilmis payload", " ".join(result["draft"]["source_notes"]))

    def test_openclaw_research_plan_filters_disallowed_tools(self):
        ollama_response = {
            "response": """
            {
              "goal": "Firma icin en guvenli public arastirma plani secildi.",
              "tool_calls": [
                {"tool": "linkedin", "reason": "Bu kullanilmamali."},
                {"tool": "website_fetch", "reason": "Resmi siteyi incelemek icin."}
              ]
            }
            """
        }

        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "false",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "http://172.16.41.43:11434",
                "OLLAMA_MODEL": "qwen2.5:14b",
            },
            clear=False,
        ):
            with patch("app.adapters.openclaw_client._call_ollama_generate", return_value=ollama_response):
                plan = plan_research_tools(
                    {
                        "company_name": "Dikkan",
                        "website": "https://www.dikkanvalve.com",
                        "keyword": "vana",
                        "sector": "metal",
                        "allowed_tools": ["website_fetch", "news_search"],
                    }
                )

        self.assertEqual(plan["provider"], "openclaw-ollama-live")
        self.assertEqual(len(plan["plan"]["tool_calls"]), 1)
        self.assertEqual(plan["plan"]["tool_calls"][0]["tool"], "website_fetch")

    def test_openclaw_company_selection_filters_unknown_candidate_ids(self):
        ollama_response = {
            "response": """
            {
              "goal": "En uygun resmi siteler secildi.",
              "selected_candidates": [
                {"candidate_id": 999, "reason": "Gecersiz aday.", "confidence": "high"},
                {"candidate_id": 2, "reason": "Resmi site gibi gorunuyor.", "confidence": "high"}
              ]
            }
            """
        }

        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "false",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "http://172.16.41.43:11434",
                "OLLAMA_MODEL": "qwen2.5:14b",
            },
            clear=False,
        ):
            with patch("app.adapters.openclaw_client._call_ollama_generate", return_value=ollama_response):
                result = select_company_candidates(
                    {
                        "keyword": "vana",
                        "sector": "metal",
                        "limit": 3,
                        "search_results": [
                            {"candidate_id": 1, "company_name": "A", "website": "https://a.example"},
                            {"candidate_id": 2, "company_name": "B", "website": "https://b.example"},
                        ],
                    }
                )

        self.assertEqual(result["provider"], "openclaw-ollama-live")
        self.assertEqual(len(result["selection"]["selected_candidates"]), 1)
        self.assertEqual(result["selection"]["selected_candidates"][0]["candidate_id"], 2)

    def test_openclaw_guided_research_builds_bundle_via_tools(self):
        raw_lead = create_manual_raw_lead(
            keyword="vana",
            company_name="Dikkan",
            website="https://www.dikkanvalve.com",
            sector="metal",
        )

        with patch.dict(
            os.environ,
            {
                "SAFE_WEB_RESEARCH_ENABLED": "true",
                "SAFE_NEWS_SEARCH_ENABLED": "false",
                "OPENCLAW_AGENT_RESEARCH_ENABLED": "true",
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "false",
                "OPENCLAW_MODEL_PROVIDER": "ollama",
                "OPENCLAW_MODEL_NAME": "qwen2.5:14b",
                "OLLAMA_BASE_URL": "http://172.16.41.43:11434",
                "OLLAMA_MODEL": "qwen2.5:14b",
            },
            clear=False,
        ):
            with patch(
                "app.services.openclaw_research_service.plan_research_tools",
                return_value={
                    "provider": "openclaw-ollama-live",
                    "mode": "sandbox",
                    "plan": {
                        "goal": "Resmi site once incelensin.",
                        "tool_calls": [
                            {"tool": "website_fetch", "reason": "Resmi site uzerinden firma ve urun sinyalini dogrulamak icin."}
                        ],
                    },
                },
            ):
                with patch(
                    "app.services.openclaw_research_service.fetch_company_website_summary",
                    return_value={
                        "source_type": "company_website",
                        "requested_url": "https://www.dikkanvalve.com",
                        "final_url": "https://www.dikkanvalve.com",
                        "title": "Dikkan Valve",
                        "meta_description": "Endustriyel vana ve denizcilik cozumleri sunar.",
                        "headings": ["Endustriyel vana", "Marine solutions"],
                        "text_excerpt": "Dikkan endustriyel vana ve marine ekipman uretir.",
                        "best_summary": "Endustriyel vana ve denizcilik cozumleri sunar.",
                        "relevance": "high",
                    },
                ):
                    with patch(
                        "app.services.openclaw_research_service.create_enrichment_draft",
                        return_value={
                            "provider": "openclaw-ollama-live",
                            "mode": "sandbox",
                            "draft": {
                                "company_summary": "Dikkan endustriyel vana ve denizcilik cozumleri sunan bir ureticidir.",
                                "recent_signal": "Sirket web sitesi incelendi ve urun odagi dogrulandi.",
                                "fit_reason": "Resmi site icerigi vana odakli satis ihtimalini destekliyor.",
                                "summary": "Resmi siteye gore satis takibine deger bir kayit.",
                                "priority": "medium",
                                "confidence": "medium",
                                "data_reliability": "high",
                                "decision_maker": {
                                    "name": None,
                                    "title": None,
                                    "email": None,
                                    "linkedin_hint": None,
                                },
                                "missing_fields": [
                                    "decision_maker_name",
                                    "decision_maker_title",
                                    "decision_maker_email",
                                ],
                                "source_notes": [
                                    "Resmi site icerigi incelendi.",
                                ],
                            },
                        },
                    ):
                        enriched = enrich_lead(raw_lead)

        self.assertEqual(enriched["research_bundle"]["mode"], "openclaw_guided")
        self.assertEqual(enriched["research_bundle"]["tool_plan"]["tool_calls"][0]["tool"], "website_fetch")
        self.assertEqual(enriched["research_bundle"]["tool_provider"], "openclaw-ollama-live")
        research_runs = store.list_research_runs(raw_lead_id=raw_lead["id"])
        self.assertEqual(research_runs[0]["mode"], "openclaw_guided")

    def test_lead_edit_filters_and_timeline(self):
        raw_lead = enrich_lead(generate_raw_leads("lead-test", "Yazilim", 1)[0])
        review_result = review_lead(
            raw_lead["id"],
            LeadReviewRequest(action="approve", reviewer_note="Onaya uygun"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        lead = review_result["lead"]

        patched_lead = patch_lead(
            lead["id"],
            LeadUpdateRequest(
                sales_owner="owner-a",
                priority="high",
                summary="Elle guncellenmis lead ozeti",
            ),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        noted_lead = create_lead_note(
            lead["id"],
            NoteCreateRequest(note="Musteriyle gorusme oncesi not"),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )

        filtered_leads = list_leads(
            owner="owner-a",
            search="gorusme oncesi not",
            limit=10,
            offset=0,
        )
        lead_timeline = get_lead_timeline(lead["id"])

        self.assertEqual(patched_lead["sales_owner"], "owner-a")
        self.assertTrue(any(item["id"] == lead["id"] for item in filtered_leads))
        self.assertTrue(any(entry["type"] == "lead_updated" for entry in lead_timeline["entries"]))
        self.assertTrue(any(entry["type"] == "user_note" for entry in lead_timeline["entries"]))
        self.assertEqual(noted_lead["id"], lead["id"])

    def test_workflow_requires_owner_and_prevents_duplicate_approval(self):
        raw_lead = enrich_lead(generate_raw_leads("workflow-guard", "Yazilim", 1)[0])
        review_result = review_lead(
            raw_lead["id"],
            LeadReviewRequest(action="approve", reviewer_note="Onaya uygun"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        lead = review_result["lead"]

        with self.assertRaises(HTTPException) as draft_before_crm_error:
            draft_first_message(
                lead["id"],
                MessageDraftRequest(channel="email"),
                actor_role=SALES_ROLE,
                actor_name="sales-user",
            )
        self.assertEqual(draft_before_crm_error.exception.status_code, 400)

        with self.assertRaises(HTTPException) as missing_owner_error:
            crm_sync(
                lead["id"],
                CRMUpdateRequest(),
                actor_role=SALES_ROLE,
                actor_name="sales-user",
            )
        self.assertEqual(missing_owner_error.exception.status_code, 400)
        self.assertIn("Sales owner is required", missing_owner_error.exception.detail)

        patched_lead = patch_lead(
            lead["id"],
            LeadUpdateRequest(sales_owner="owner-b"),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        self.assertEqual(patched_lead["sales_owner"], "owner-b")

        crm_sync(
            lead["id"],
            CRMUpdateRequest(),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        draft_first_message(
            lead["id"],
            MessageDraftRequest(channel="email"),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        approve_first_message(
            lead["id"],
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )

        with self.assertRaises(HTTPException) as duplicate_approval_error:
            approve_first_message(
                lead["id"],
                actor_role=SALES_ROLE,
                actor_name="sales-user",
            )
        self.assertEqual(duplicate_approval_error.exception.status_code, 400)
        self.assertIn("Only draft messages can be approved", duplicate_approval_error.exception.detail)

    def test_follow_up_can_restart_after_needs_follow_up_reply(self):
        raw_lead = enrich_lead(generate_raw_leads("follow-up-guard", "Lojistik", 1)[0])
        review_result = review_lead(
            raw_lead["id"],
            LeadReviewRequest(action="approve", reviewer_note="Akisa uygun"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        lead = review_result["lead"]

        patch_lead(
            lead["id"],
            LeadUpdateRequest(sales_owner="owner-c"),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        crm_sync(
            lead["id"],
            CRMUpdateRequest(),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        draft_first_message(
            lead["id"],
            MessageDraftRequest(channel="email"),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        approve_first_message(
            lead["id"],
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        send_first_message(
            lead["id"],
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        save_reply(
            lead["id"],
            ReplyUpdateRequest(reply_type="needs_follow_up", detail="Bir hafta sonra tekrar donelim"),
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )

        follow_up = draft_follow_up(
            lead["id"],
            actor_role=SALES_ROLE,
            actor_name="sales-user",
        )
        self.assertEqual(follow_up["outreach_status"], "follow_up_draft_ready")
        self.assertEqual(follow_up["follow_up_message"]["status"], "draft")

    def test_role_permissions_block_wrong_actions(self):
        raw_lead = enrich_lead(generate_raw_leads("role-guard", "Metal", 1)[0])

        with self.assertRaises(HTTPException) as viewer_raw_error:
            patch_raw_lead(
                raw_lead["id"],
                RawLeadUpdateRequest(summary="yetkisiz deneme"),
                actor_role="viewer",
                actor_name="viewer-user",
            )
        self.assertEqual(viewer_raw_error.exception.status_code, 403)

        review_result = review_lead(
            raw_lead["id"],
            LeadReviewRequest(action="approve", reviewer_note="Onaya uygun"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        lead = review_result["lead"]

        with self.assertRaises(HTTPException) as reviewer_sales_error:
            patch_lead(
                lead["id"],
                LeadUpdateRequest(summary="sales alani"),
                actor_role=REVIEWER_ROLE,
                actor_name="reviewer-user",
            )
        self.assertEqual(reviewer_sales_error.exception.status_code, 403)

    def test_ai_draft_stays_pending_until_manual_approval(self):
        raw_lead = generate_raw_leads("ai-draft-test", "Enerji", 1)[0]

        draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        persisted_raw_lead = store.get_raw_lead(raw_lead["id"])
        drafts = get_raw_lead_drafts(raw_lead["id"])
        preview = get_ai_draft_preview(draft["id"])

        self.assertEqual(draft["status"], "pending")
        self.assertEqual(persisted_raw_lead["research_status"], "pending")
        self.assertEqual(persisted_raw_lead["status"], "new")
        self.assertEqual(len(drafts), 1)
        self.assertGreater(preview["changed_fields_total"], 0)
        self.assertTrue(any(change["changed"] for change in preview["changes"]))
        self.assertEqual(draft["request_payload"]["raw_lead_id"], raw_lead["id"])
        self.assertNotIn("personal_notes", draft["request_payload"])
        self.assertNotIn("review_note", draft["request_payload"])
        self.assertIn("draft", draft["response_payload"])
        self.assertEqual(draft["response_payload"]["meta"]["review"], None)

        approval_result = approve_ai_draft(
            draft["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        approved_raw_lead = approval_result["raw_lead"]
        approved_draft = approval_result["draft"]

        self.assertEqual(approved_draft["status"], "approved")
        self.assertEqual(approved_draft["approved_by"], "reviewer-user")
        self.assertEqual(approved_draft["response_payload"]["meta"]["review"]["status"], "approved")
        self.assertEqual(approved_raw_lead["research_status"], "completed")
        self.assertEqual(approved_raw_lead["status"], "needs_review")
        self.assertTrue(any("AI enrichment draft approved" in note for note in approved_raw_lead["personal_notes"]))

    def test_ai_draft_can_be_rejected_without_mutating_raw_lead(self):
        raw_lead = generate_raw_leads("ai-reject-test", "Kimya", 1)[0]

        draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        rejected = reject_ai_draft(
            draft["id"],
            AIDraftReviewRequest(note="Bu taslak yetersiz bulundu"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        persisted_raw_lead = store.get_raw_lead(raw_lead["id"])

        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["response_payload"]["meta"]["review"]["status"], "rejected")
        self.assertEqual(persisted_raw_lead["research_status"], "pending")
        self.assertEqual(persisted_raw_lead["status"], "new")

        with self.assertRaises(HTTPException) as approve_rejected_error:
            approve_ai_draft(
                draft["id"],
                actor_role=REVIEWER_ROLE,
                actor_name="reviewer-user",
            )
        self.assertEqual(approve_rejected_error.exception.status_code, 400)

    def test_ai_draft_history_can_compare_latest_with_previous_version(self):
        raw_lead = generate_raw_leads("ai-compare-test", "Otomotiv", 1)[0]

        first_draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        first_draft["response_payload"]["draft"]["summary"] = "Ilk taslak ozeti"
        first_draft["response_payload"]["draft"]["priority"] = "low"
        store.save_ai_draft(first_draft)

        second_draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        comparison = compare_ai_drafts(second_draft["id"], first_draft["id"])

        self.assertEqual(comparison["base_draft"]["id"], second_draft["id"])
        self.assertEqual(comparison["compare_draft"]["id"], first_draft["id"])
        self.assertGreater(comparison["changed_fields_total"], 0)
        self.assertTrue(any(change["field"] == "summary" and change["changed"] for change in comparison["changes"]))
        self.assertTrue(any(change["field"] == "priority" and change["changed"] for change in comparison["changes"]))
        self.assertEqual(store.get_ai_draft(first_draft["id"])["status"], "superseded")

    def test_ai_draft_can_be_archived_after_review_state(self):
        raw_lead = generate_raw_leads("ai-archive-test", "Savunma", 1)[0]

        first_draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        second_draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )

        archived = archive_ai_draft(
            first_draft["id"],
            AIDraftReviewRequest(note="Eski versiyon arsive kaldirildi"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        visible_drafts = get_raw_lead_drafts(raw_lead["id"])
        all_drafts = get_raw_lead_drafts(raw_lead["id"], include_archived=True)

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(archived["response_payload"]["meta"]["archive"]["status"], "archived")
        self.assertEqual(archived["response_payload"]["meta"]["review"]["status"], "superseded")
        self.assertEqual(len(visible_drafts), 1)
        self.assertEqual(visible_drafts[0]["id"], second_draft["id"])
        self.assertEqual(len(all_drafts), 2)

    def test_pending_ai_draft_cannot_be_archived(self):
        raw_lead = generate_raw_leads("ai-archive-pending", "Plastik", 1)[0]

        draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )

        with self.assertRaises(HTTPException) as pending_archive_error:
            archive_ai_draft(
                draft["id"],
                AIDraftReviewRequest(note="Erken arsiv denemesi"),
                actor_role=REVIEWER_ROLE,
                actor_name="reviewer-user",
            )
        self.assertEqual(pending_archive_error.exception.status_code, 400)

    def test_archived_ai_draft_can_be_restored_to_previous_status(self):
        raw_lead = generate_raw_leads("ai-restore-test", "Makine", 1)[0]

        first_draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )

        archive_ai_draft(
            first_draft["id"],
            AIDraftReviewRequest(note="Eski draft gizlendi"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        restored = restore_ai_draft(
            first_draft["id"],
            AIDraftReviewRequest(note="Karsilastirma icin geri acildi"),
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )
        visible_drafts = get_raw_lead_drafts(raw_lead["id"])

        self.assertEqual(restored["status"], "superseded")
        self.assertEqual(restored["response_payload"]["meta"]["archive"]["previous_status"], "superseded")
        self.assertEqual(restored["response_payload"]["meta"]["restore"]["status"], "restored")
        self.assertEqual(restored["response_payload"]["meta"]["restore"]["restored_to"], "superseded")
        self.assertEqual(len(visible_drafts), 2)

    def test_non_archived_ai_draft_cannot_be_restored(self):
        raw_lead = generate_raw_leads("ai-restore-guard", "Elektrik", 1)[0]

        draft = create_raw_lead_enrichment_draft(
            raw_lead["id"],
            actor_role=REVIEWER_ROLE,
            actor_name="reviewer-user",
        )

        with self.assertRaises(HTTPException) as restore_guard_error:
            restore_ai_draft(
                draft["id"],
                AIDraftReviewRequest(note="Yanlis restore denemesi"),
                actor_role=REVIEWER_ROLE,
                actor_name="reviewer-user",
            )
        self.assertEqual(restore_guard_error.exception.status_code, 400)

    def test_openclaw_preview_exposes_safe_request_and_latest_adapter_output(self):
        raw_lead = generate_raw_leads("openclaw-preview", "Enerji", 1)[0]

        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "true",
            },
            clear=False,
        ):
            preview_before = get_raw_lead_openclaw_preview(raw_lead["id"])
        self.assertEqual(preview_before["runtime"]["provider"], "openclaw")
        self.assertEqual(preview_before["runtime"]["mode"], "sandbox")
        self.assertEqual(preview_before["runtime"]["setup_state"], "sandbox_ready")
        self.assertTrue(preview_before["runtime"]["dry_run_only"])
        self.assertTrue(preview_before["runtime"]["can_generate_drafts"])
        self.assertEqual(preview_before["request_payload"]["raw_lead_id"], raw_lead["id"])
        self.assertNotIn("personal_notes", preview_before["request_payload"])
        self.assertIsNone(preview_before["latest_draft"])

        with patch.dict(
            os.environ,
            {
                "OPENCLAW_MODE": "sandbox",
                "OPENCLAW_DRY_RUN_ONLY": "true",
            },
            clear=False,
        ):
            create_raw_lead_enrichment_draft(
                raw_lead["id"],
                actor_role=REVIEWER_ROLE,
                actor_name="reviewer-user",
            )
            preview_after = get_raw_lead_openclaw_preview(raw_lead["id"])

        self.assertEqual(preview_after["drafts_total"], 1)
        self.assertEqual(preview_after["latest_draft"]["status"], "pending")
        self.assertIn("draft", preview_after["latest_draft"]["response_payload"])


if __name__ == "__main__":
    unittest.main()
