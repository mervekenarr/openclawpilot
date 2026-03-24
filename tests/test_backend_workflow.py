import os
import unittest
from uuid import uuid4
from unittest.mock import patch

from fastapi import HTTPException

from app import sqlite_store, store
from app.adapters.openclaw_client import get_runtime_info
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
from app.services.openclaw_service import enrich_lead, generate_raw_leads

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

    def test_openclaw_preview_exposes_safe_request_and_latest_mock_output(self):
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
