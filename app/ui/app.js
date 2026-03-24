const state = {
    keywords: [],
    rawLeads: [],
    leads: [],
    summary: null,
    system: null,
    selected: null,
    actor: loadActorPreferences(),
    detail: {
        loading: false,
        error: null,
        rawTimelineById: {},
        leadTimelineById: {},
        rawDraftsById: {},
        rawDraftPreviewById: {},
        rawDraftComparisonById: {},
        rawDraftCompareSelectionById: {},
        rawDraftHistoryModeById: {},
        openclawPreviewById: {},
        timelineType: "",
        timelineSearch: "",
    },
    filters: {
        rawStatus: "",
        rawResearchStatus: "",
        rawPriority: "",
        rawReliability: "",
        leadStatus: "",
        leadCrmStatus: "",
        leadOutreachStatus: "",
        leadPriority: "",
        leadOwner: "",
        rawSearch: "",
        leadSearch: "",
    },
};

const elements = {};
const searchTimers = {
    raw: null,
    lead: null,
    detail: null,
    actor: null,
};

document.addEventListener("DOMContentLoaded", () => {
    assignElements();
    bindEvents();
    refreshDashboard("Dashboard hazirlandi.");
});

function assignElements() {
    elements.intakeForm = document.getElementById("intakeForm");
    elements.refreshButton = document.getElementById("refreshButton");
    elements.statusBanner = document.getElementById("statusBanner");
    elements.actorRoleSelect = document.getElementById("actorRoleSelect");
    elements.actorNameInput = document.getElementById("actorNameInput");
    elements.keywordRail = document.getElementById("keywordRail");
    elements.systemPanel = document.getElementById("systemPanel");
    elements.summaryGrid = document.getElementById("summaryGrid");
    elements.rawLeadList = document.getElementById("rawLeadList");
    elements.leadList = document.getElementById("leadList");
    elements.detailPanel = document.getElementById("detailPanel");
    elements.rawStatusFilter = document.getElementById("rawStatusFilter");
    elements.rawResearchStatusFilter = document.getElementById("rawResearchStatusFilter");
    elements.rawPriorityFilter = document.getElementById("rawPriorityFilter");
    elements.rawReliabilityFilter = document.getElementById("rawReliabilityFilter");
    elements.leadStatusFilter = document.getElementById("leadStatusFilter");
    elements.leadCrmStatusFilter = document.getElementById("leadCrmStatusFilter");
    elements.leadOutreachStatusFilter = document.getElementById("leadOutreachStatusFilter");
    elements.leadPriorityFilter = document.getElementById("leadPriorityFilter");
    elements.leadOwnerFilter = document.getElementById("leadOwnerFilter");
    elements.rawSearchFilter = document.getElementById("rawSearchFilter");
    elements.leadSearchFilter = document.getElementById("leadSearchFilter");
    if (elements.actorRoleSelect) {
        elements.actorRoleSelect.value = state.actor.role;
    }
    if (elements.actorNameInput) {
        elements.actorNameInput.value = state.actor.name;
    }
}

function bindEvents() {
    elements.intakeForm.addEventListener("submit", handleIntakeSubmit);
    elements.refreshButton.addEventListener("click", () => refreshDashboard("Veriler yenilendi."));
    elements.rawLeadList.addEventListener("click", handleRawLeadClick);
    elements.leadList.addEventListener("click", handleLeadClick);
    elements.detailPanel.addEventListener("submit", handleDetailSubmit);
    elements.detailPanel.addEventListener("input", handleDetailInput);
    elements.detailPanel.addEventListener("change", handleDetailInput);
    if (elements.actorRoleSelect) {
        elements.actorRoleSelect.addEventListener("change", handleActorChange);
    }
    if (elements.actorNameInput) {
        elements.actorNameInput.addEventListener("input", handleActorChange);
    }
    elements.rawStatusFilter.addEventListener("change", handleFilterChange);
    elements.rawResearchStatusFilter.addEventListener("change", handleFilterChange);
    elements.rawPriorityFilter.addEventListener("change", handleFilterChange);
    elements.rawReliabilityFilter.addEventListener("change", handleFilterChange);
    elements.leadStatusFilter.addEventListener("change", handleFilterChange);
    elements.leadCrmStatusFilter.addEventListener("change", handleFilterChange);
    elements.leadOutreachStatusFilter.addEventListener("change", handleFilterChange);
    elements.leadPriorityFilter.addEventListener("change", handleFilterChange);
    elements.rawSearchFilter.addEventListener("input", handleSearchInput);
    elements.leadOwnerFilter.addEventListener("input", handleSearchInput);
    elements.leadSearchFilter.addEventListener("input", handleSearchInput);
}

async function refreshDashboard(successMessage) {
    setStatus("Veriler yukleniyor...", "pending");

    try {
        const [keywords, rawLeads, leads, summary, system] = await Promise.all([
            apiRequest("/keywords"),
            apiRequest(
                `/raw-leads${toQueryString({
                    status: state.filters.rawStatus,
                    research_status: state.filters.rawResearchStatus,
                    priority: state.filters.rawPriority,
                    data_reliability: state.filters.rawReliability,
                    search: state.filters.rawSearch,
                })}`
            ),
            apiRequest(
                `/leads${toQueryString({
                    status: state.filters.leadStatus,
                    crm_status: state.filters.leadCrmStatus,
                    outreach_status: state.filters.leadOutreachStatus,
                    priority: state.filters.leadPriority,
                    owner: state.filters.leadOwner,
                    search: state.filters.leadSearch,
                })}`
            ),
            apiRequest("/pipeline/summary"),
            apiRequest("/system/info"),
        ]);

        state.keywords = keywords;
        state.rawLeads = rawLeads;
        state.leads = leads;
        state.summary = summary;
        state.system = system;

        normalizeSelection();
        renderDashboard();
        await hydrateSelectedTimeline({ silent: true });
        await hydrateSelectedOpenClawPreview({ silent: true });
        await hydrateSelectedAIDrafts({ silent: true });
        setStatus(successMessage || "Dashboard guncellendi.", "success");
    } catch (error) {
        setStatus(error.message, "error");
    }
}

function handleFilterChange() {
    syncFiltersFromInputs();
    refreshDashboard("Filtreler guncellendi.");
}

function handleSearchInput(event) {
    const isRawGroup = [
        elements.rawSearchFilter,
    ].includes(event.target);
    const timerKey = isRawGroup ? "raw" : "lead";

    if (searchTimers[timerKey]) {
        window.clearTimeout(searchTimers[timerKey]);
    }

    searchTimers[timerKey] = window.setTimeout(() => {
        syncFiltersFromInputs();
        refreshDashboard("Arama filtreleri guncellendi.");
    }, 260);
}

function handleActorChange(event) {
    if (event.target === elements.actorNameInput) {
        if (searchTimers.actor) {
            window.clearTimeout(searchTimers.actor);
        }

        searchTimers.actor = window.setTimeout(() => {
            syncActorFromInputs();
            refreshDashboard("Actor bilgisi guncellendi.");
        }, 220);
        return;
    }

    syncActorFromInputs();
    refreshDashboard("Rol guncellendi.");
}

async function handleIntakeSubmit(event) {
    event.preventDefault();

    const formData = new FormData(elements.intakeForm);
    const keyword = String(formData.get("keyword") || "").trim();
    const sector = String(formData.get("sector") || "").trim();
    const limit = Number(formData.get("limit") || 5);

    if (!keyword) {
        setStatus("Keyword gerekli.", "error");
        return;
    }

    setStatus("Keyword kaydediliyor ve mock crawl baslatiliyor...", "pending");

    try {
        await apiRequest("/keywords", {
            method: "POST",
            body: { keyword },
        });

        await apiRequest("/crawl/start", {
            method: "POST",
            body: {
                keyword,
                sector: sector || null,
                limit,
            },
        });

        elements.intakeForm.reset();
        await refreshDashboard(`"${keyword}" icin yeni raw leadler uretildi.`);
    } catch (error) {
        setStatus(error.message, "error");
    }
}

async function handleRawLeadClick(event) {
    const button = event.target.closest("button[data-action]");
    const card = event.target.closest("[data-raw-id]");

    if (!card) {
        return;
    }

    const rawLeadId = Number(card.dataset.rawId);
    setSelectedRecord({ kind: "raw", id: rawLeadId });
    renderDetailPanel();
    void hydrateSelectedTimeline({ silent: true });
    void hydrateSelectedOpenClawPreview({ silent: true });
    void hydrateSelectedAIDrafts({ silent: true });

    if (!button) {
        return;
    }

    const action = button.dataset.action;

    try {
        if (action === "research") {
            setStatus("Raw lead arastiriliyor...", "pending");
            await apiRequest(`/raw-leads/${rawLeadId}/research`, { method: "POST" });
        }

        if (action.startsWith("review-")) {
            const reviewAction = action.replace("review-", "");
            const reviewerNote = window.prompt("Opsiyonel review notu", "") || null;

            setStatus(`Raw lead ${reviewAction} ediliyor...`, "pending");
            await apiRequest(`/raw-leads/${rawLeadId}/review`, {
                method: "POST",
                body: {
                    action: reviewAction,
                    reviewer_note: reviewerNote,
                },
            });
        }

        await refreshDashboard("Raw lead guncellendi.");
    } catch (error) {
        setStatus(error.message, "error");
    }
}

async function handleLeadClick(event) {
    const button = event.target.closest("button[data-action]");
    const card = event.target.closest("[data-lead-id]");

    if (!card) {
        return;
    }

    const leadId = Number(card.dataset.leadId);
    setSelectedRecord({ kind: "lead", id: leadId });
    renderDetailPanel();
    void hydrateSelectedTimeline({ silent: true });

    if (!button) {
        return;
    }

    const action = button.dataset.action;
    const owner = String(card.querySelector('[data-role="owner"]')?.value || "").trim();
    const channel = String(card.querySelector('[data-role="channel"]')?.value || "email");
    const replyType = String(card.querySelector('[data-role="reply-type"]')?.value || "meeting_request");

    try {
        if (action === "crm-sync") {
            setStatus("Lead CRM durumuna geciriliyor...", "pending");
            await apiRequest(`/leads/${leadId}/crm-sync`, {
                method: "POST",
                body: { owner: owner || null },
            });
        }

        if (action === "draft-first-message") {
            setStatus("Ilk mesaj taslagi olusturuluyor...", "pending");
            await apiRequest(`/leads/${leadId}/draft-first-message`, {
                method: "POST",
                body: { channel },
            });
        }

        if (action === "approve-first-message") {
            setStatus("Ilk mesaj onaylaniyor...", "pending");
            await apiRequest(`/leads/${leadId}/approve-first-message`, { method: "POST" });
        }

        if (action === "mark-first-message-sent") {
            setStatus("Ilk mesaj gonderildi olarak isaretleniyor...", "pending");
            await apiRequest(`/leads/${leadId}/mark-first-message-sent`, { method: "POST" });
        }

        if (action === "draft-follow-up") {
            setStatus("Follow-up taslagi hazirlaniyor...", "pending");
            await apiRequest(`/leads/${leadId}/draft-follow-up`, { method: "POST" });
        }

        if (action === "approve-follow-up") {
            setStatus("Follow-up onaylaniyor...", "pending");
            await apiRequest(`/leads/${leadId}/approve-follow-up`, { method: "POST" });
        }

        if (action === "mark-follow-up-sent") {
            setStatus("Follow-up gonderildi olarak isaretleniyor...", "pending");
            await apiRequest(`/leads/${leadId}/mark-follow-up-sent`, { method: "POST" });
        }

        if (action === "record-reply") {
            const detail = window.prompt("Opsiyonel yanit notu", "") || null;

            setStatus("Musteri yaniti kaydediliyor...", "pending");
            await apiRequest(`/leads/${leadId}/record-reply`, {
                method: "POST",
                body: {
                    reply_type: replyType,
                    detail,
                },
            });
        }

        await refreshDashboard("Lead guncellendi.");
    } catch (error) {
        setStatus(error.message, "error");
    }
}

async function handleDetailSubmit(event) {
    event.preventDefault();

    const form = event.target.closest("form[data-detail-form]");
    if (!form || !state.selected) {
        return;
    }

    const action = form.dataset.detailForm;

    try {
        if (action === "raw-research") {
            await submitRawLeadResearch();
        }

        if (action === "raw-review") {
            await submitRawLeadReview(form);
        }

        if (action === "raw-update") {
            await submitRawLeadUpdate(form);
        }

        if (action === "raw-note") {
            await submitRawLeadNote(form);
        }

        if (action === "lead-update") {
            await submitLeadUpdate(form);
        }

        if (action === "lead-note") {
            await submitLeadNote(form);
        }

        if (action === "raw-ai-create") {
            await submitRawLeadAIDraft(form);
        }

        if (action === "raw-ai-approve") {
            await submitRawLeadAIApproval(form);
        }

        if (action === "raw-ai-reject") {
            await submitRawLeadAIReject(form);
        }

        if (action === "raw-ai-archive") {
            await submitRawLeadAIArchive(form);
        }

        if (action === "raw-ai-restore") {
            await submitRawLeadAIRestore(form);
        }
    } catch (error) {
        setStatus(error.message, "error");
    }
}

function handleDetailInput(event) {
    const control = event.target.closest("[data-detail-filter]");

    if (!control) {
        return;
    }

    if (control.dataset.detailFilter === "draft-history-mode") {
        handleDraftHistoryModeSelection(control);
        return;
    }

    if (control.dataset.detailFilter === "draft-compare-id") {
        handleDraftCompareSelection(control);
        return;
    }

    if (searchTimers.detail) {
        window.clearTimeout(searchTimers.detail);
    }

    const applyFilter = () => {
        state.detail.timelineType = getDetailFilterValue("timeline-type");
        state.detail.timelineSearch = getDetailFilterValue("timeline-search");
        renderDetailPanel();
    };

    if (control.dataset.detailFilter === "timeline-search") {
        searchTimers.detail = window.setTimeout(applyFilter, 220);
        return;
    }

    applyFilter();
}

function handleDraftHistoryModeSelection(control) {
    if (!state.selected || state.selected.kind !== "raw") {
        return;
    }

    const rawLeadId = state.selected.id;
    state.detail.rawDraftHistoryModeById[rawLeadId] = control.value === "all" ? "all" : "active";
    delete state.detail.rawDraftComparisonById[rawLeadId];
    delete state.detail.rawDraftCompareSelectionById[rawLeadId];
    renderDetailPanel();
    void hydrateSelectedAIDrafts({ silent: true });
}

function handleDraftCompareSelection(control) {
    if (!state.selected || state.selected.kind !== "raw") {
        return;
    }

    const rawLeadId = state.selected.id;
    const compareDraftId = Number(control.value || 0);
    const drafts = state.detail.rawDraftsById[rawLeadId] || [];
    const latestDraft = drafts[0];

    state.detail.rawDraftCompareSelectionById[rawLeadId] = compareDraftId || null;

    if (!latestDraft || !compareDraftId) {
        delete state.detail.rawDraftComparisonById[rawLeadId];
        renderDetailPanel();
        return;
    }

    delete state.detail.rawDraftComparisonById[rawLeadId];
    renderDetailPanel();
    void hydrateAIDraftComparison(latestDraft.id, compareDraftId, { rawLeadId, silent: true });
}

async function apiRequest(url, options = {}) {
    const requestOptions = {
        method: options.method || "GET",
        headers: {
            "Accept": "application/json",
            "X-Actor-Role": state.actor.role,
            "X-Actor-Name": state.actor.name,
        },
    };

    if (options.body) {
        requestOptions.headers["Content-Type"] = "application/json";
        requestOptions.body = JSON.stringify(options.body);
    }

    const response = await fetch(url, requestOptions);
    const payload = await parseResponse(response);

    if (!response.ok) {
        throw new Error(payload.detail || payload.message || "Istek basarisiz oldu.");
    }

    return payload;
}

async function parseResponse(response) {
    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        return response.json();
    }

    return { message: await response.text() };
}

function renderDashboard() {
    renderActorState();
    renderKeywords();
    renderSystemPanel();
    if (elements.summaryGrid) {
        renderSummary();
    }
    renderRawLeads();
    renderLeads();
    renderDetailPanel();
}

function renderActorState() {
    const submitButton = elements.intakeForm.querySelector('button[type="submit"]');

    if (submitButton) {
        submitButton.disabled = !canManageIntake();
    }
}

function renderSystemPanel() {
    const runtime = state.system?.runtime || {};
    const health = state.system?.health || {};
    const connection = runtime.connection || {};
    const ai = state.system?.ai || {};

    const cards = [
        {
            title: "Uygulama",
            body: `${translateUiValue(runtime.backend || "bilinmiyor")} / ${health.ok ? "hazir" : "problem var"}`,
        },
        {
            title: "OpenClaw",
            body: formatOpenClawSetup(ai),
        },
        {
            title: "Baglanti",
            body: ai.recommended_next_step || formatConnection(connection),
        },
    ];

    elements.systemPanel.innerHTML = cards
        .map(
            (card) => `
                <article class="system-card">
                    <strong>${escapeHtml(card.title)}</strong>
                    <p>${escapeHtml(card.body)}</p>
                </article>
            `
        )
        .join("");
}

function renderKeywords() {
    if (!state.keywords.length) {
        elements.keywordRail.innerHTML = '<span class="keyword-pill empty">Henuz kayit yok.</span>';
        return;
    }

    elements.keywordRail.innerHTML = state.keywords
        .map((keyword) => `<span class="keyword-pill">${escapeHtml(keyword.keyword)}</span>`)
        .join("");
}

function renderSummary() {
    if (!elements.summaryGrid) {
        return;
    }

    const summary = state.summary || {};

    const cards = [
        {
            label: "Keyword",
            value: summary.keywords_total || 0,
            meta: `${(state.keywords || []).slice(0, 3).map((item) => item.keyword).join(" / ") || "Henuz tanim yok"}`,
        },
        {
            label: "Raw leads",
            value: summary.raw_leads_total || 0,
            meta: `Yeni: ${(summary.raw_lead_status || {}).new || 0} / Review: ${(summary.raw_lead_status || {}).needs_review || 0}`,
        },
        {
            label: "Leadler",
            value: summary.approved_leads_total || 0,
            meta: `CRM synced: ${(summary.crm_status || {}).synced || 0} / Reply: ${(summary.outreach_status || {}).reply_received || 0}`,
        },
    ];

    elements.summaryGrid.innerHTML = cards
        .map(
            (card) => `
                <article class="metric-card">
                    <p class="metric-label">${escapeHtml(card.label)}</p>
                    <p class="metric-value">${escapeHtml(String(card.value))}</p>
                    <p class="metric-meta">${escapeHtml(card.meta)}</p>
                </article>
            `
        )
        .join("");
}

function renderRawLeads() {
    if (!state.rawLeads.length) {
        elements.rawLeadList.innerHTML = renderEmptyState("Tarama baslatildiginda ham leadler burada listelenecek.");
        return;
    }

    elements.rawLeadList.innerHTML = state.rawLeads
        .map((rawLead) => {
            const isSelected = state.selected?.kind === "raw" && state.selected.id === rawLead.id;
            const researchDone = rawLead.research_status === "completed";
            const missingCount = (rawLead.missing_fields || []).length;

            return `
                <article class="lead-card ${isSelected ? "is-selected" : ""}" data-raw-id="${rawLead.id}">
                    <div class="card-top">
                        <div>
                            <p class="card-kicker">Ham lead #${rawLead.id}</p>
                            <h3>${escapeHtml(rawLead.company_name)}</h3>
                        </div>
                        <div class="badge-row">
                            ${renderBadge(rawLead.status)}
                            ${renderBadge(rawLead.research_status)}
                            ${rawLead.priority ? renderBadge(rawLead.priority) : ""}
                        </div>
                    </div>
                    <p class="card-copy">${escapeHtml(rawLead.summary || rawLead.company_summary || "Arastirma bekliyor.")}</p>
                    <div class="card-footer">
                        <p class="mini-note">
                            ${escapeHtml(rawLead.keyword || "-")}
                            •
                            ${escapeHtml(rawLead.sector || "-")}
                            •
                            eksik: ${escapeHtml(String(missingCount))}
                        </p>
                        <button class="tiny-button accent" data-action="research" ${researchDone || !canWriteRawLeads() ? "disabled" : ""}>Arastir</button>
                    </div>
                </article>
            `;
        })
        .join("");
}

function renderLeads() {
    if (!state.leads.length) {
        elements.leadList.innerHTML = renderEmptyState("Onaylanan leadler burada gorunur.");
        return;
    }

    elements.leadList.innerHTML = state.leads
        .map((lead) => {
            const isSelected = state.selected?.kind === "lead" && state.selected.id === lead.id;
            const firstMessage = lead.first_message || null;
            const followUpMessage = lead.follow_up_message || null;
            const canRecordReply = ["awaiting_reply", "follow_up_sent"].includes(lead.outreach_status);
            const workflowHint = getLeadHint(lead);

            return `
                <article class="lead-card ${isSelected ? "is-selected" : ""}" data-lead-id="${lead.id}">
                    <div class="card-top">
                        <div>
                            <p class="card-kicker">Lead #${lead.id}</p>
                            <h3>${escapeHtml(lead.company_name)}</h3>
                        </div>
                        <div class="badge-row">
                            ${renderBadge(lead.status)}
                            ${renderBadge(lead.crm_status)}
                            ${renderBadge(lead.outreach_status)}
                        </div>
                    </div>
                    <p class="card-copy">${escapeHtml(lead.summary || lead.company_summary || "Lead detaylari hazir.")}</p>
                    <dl class="meta-grid">
                        ${renderMetaItem("Sektor", lead.sector)}
                        ${renderMetaItem("Oncelik", lead.priority)}
                        ${renderMetaItem("Guven", translateUiValue(lead.confidence))}
                        ${renderMetaItem("Sorumlu", lead.sales_owner || "atanmadi")}
                    </dl>
                    <div class="action-stack">
                        <p class="workflow-hint">${escapeHtml(workflowHint)}</p>
                        <div class="mini-control">
                            <span>CRM sorumlusu</span>
                            <div class="action-row">
                                <input data-role="owner" type="text" value="${escapeHtml(lead.sales_owner || "")}" placeholder="demo-user">
                                <button class="tiny-button accent" data-action="crm-sync" ${!canWriteLeads() ? "disabled" : ""}>CRM aktar</button>
                            </div>
                        </div>
                        <div class="mini-control">
                            <span>Ilk temas kanali</span>
                            <div class="action-row">
                                <select data-role="channel">
                                    <option value="email" ${firstMessage?.channel === "email" ? "selected" : ""}>e-posta</option>
                                    <option value="linkedin" ${firstMessage?.channel === "linkedin" ? "selected" : ""}>linkedin</option>
                                </select>
                                <button class="tiny-button accent" data-action="draft-first-message" ${lead.crm_status !== "synced" || !canWriteLeads() ? "disabled" : ""}>Ilk taslagi olustur</button>
                                <button class="tiny-button" data-action="approve-first-message" ${firstMessage?.status !== "draft" || !canWriteLeads() ? "disabled" : ""}>Taslagi onayla</button>
                                <button class="tiny-button warm" data-action="mark-first-message-sent" ${firstMessage?.status !== "approved" || !canWriteLeads() ? "disabled" : ""}>Gonderildi</button>
                            </div>
                        </div>
                        <div class="mini-control">
                            <span>Follow-up dongusu</span>
                            <div class="action-row">
                                <button class="tiny-button accent" data-action="draft-follow-up" ${!["awaiting_reply", "follow_up_due"].includes(lead.outreach_status) || !canWriteLeads() ? "disabled" : ""}>Takip taslagi</button>
                                <button class="tiny-button" data-action="approve-follow-up" ${followUpMessage?.status !== "draft" || !canWriteLeads() ? "disabled" : ""}>Takibi onayla</button>
                                <button class="tiny-button warm" data-action="mark-follow-up-sent" ${followUpMessage?.status !== "approved" || !canWriteLeads() ? "disabled" : ""}>Takip gonderildi</button>
                            </div>
                        </div>
                        <div class="mini-control">
                            <span>Reply kaydi</span>
                            <div class="action-row">
                                <select data-role="reply-type">
                                    <option value="meeting_request">meeting_request</option>
                                    <option value="positive">positive</option>
                                    <option value="needs_follow_up">needs_follow_up</option>
                                    <option value="negative">negative</option>
                                </select>
                                <button class="tiny-button accent" data-action="record-reply" ${!canRecordReply || !canWriteLeads() ? "disabled" : ""}>Yaniti kaydet</button>
                            </div>
                        </div>
                    </div>
                </article>
            `;
        })
        .join("");
}

function renderRawLeadPrimaryActions(rawLead) {
    const researchDone = rawLead.research_status === "completed";
    const reviewReady = ["needs_review", "needs_revision", "on_hold"].includes(rawLead.status);

    return `
        <div class="detail-note-stack">
            <form class="detail-form detail-form-inline" data-detail-form="raw-research">
                <button class="primary-button detail-button" type="submit" ${researchDone || !canWriteRawLeads() ? "disabled" : ""}>1. Arastirmayi calistir</button>
            </form>
            <form class="detail-form detail-form-inline" data-detail-form="raw-review">
                <input type="hidden" name="review_action" value="approve">
                <label class="detail-field detail-field-wide">
                    <span>Review notu</span>
                    <textarea name="reviewer_note" rows="3" placeholder="Kisa karar notu"></textarea>
                </label>
                <div class="action-row">
                    <button class="tiny-button accent" type="submit" onclick="this.form.review_action.value='approve'" ${!reviewReady || !canWriteRawLeads() ? "disabled" : ""}>Approve</button>
                    <button class="tiny-button warm" type="submit" onclick="this.form.review_action.value='hold'" ${!reviewReady || !canWriteRawLeads() ? "disabled" : ""}>Beklet</button>
                    <button class="tiny-button" type="submit" onclick="this.form.review_action.value='revise'" ${!reviewReady || !canWriteRawLeads() ? "disabled" : ""}>Revize iste</button>
                    <button class="tiny-button danger" type="submit" onclick="this.form.review_action.value='reject'" ${!reviewReady || !canWriteRawLeads() ? "disabled" : ""}>Reject</button>
                </div>
            </form>
        </div>
    `;
}

function renderDetailPanel() {
    const selected = state.selected;

    if (!selected) {
        elements.detailPanel.innerHTML = "Soldan bir kayit sec.";
        return;
    }

    if (selected.kind === "raw") {
        const rawLead = state.rawLeads.find((item) => item.id === selected.id);

        if (!rawLead) {
            elements.detailPanel.innerHTML = "Secilen raw lead artik listede yok.";
            return;
        }

        const decisionMaker = rawLead.decision_maker || {};
        const timelineEntries = state.detail.rawTimelineById[rawLead.id] || [];
        const aiDrafts = state.detail.rawDraftsById[rawLead.id] || [];
        elements.detailPanel.innerHTML = `
            <div class="detail-card">
                <div class="detail-block">
                    <p class="section-kicker">Raw lead #${rawLead.id}</p>
                    <h3>${escapeHtml(rawLead.company_name)}</h3>
                    <div class="badge-row">
                        ${renderBadge(rawLead.status)}
                        ${renderBadge(rawLead.research_status)}
                        ${rawLead.data_reliability ? renderBadge(rawLead.data_reliability) : ""}
                    </div>
                    <p class="detail-copy">${escapeHtml(rawLead.company_summary || "Arastirma tamamlandiginda bu alan dolacak.")}</p>
                    <p class="detail-copy detail-hint">${escapeHtml(getRawLeadHint(rawLead))}</p>
                </div>
                <div class="detail-block">
                    <h4>Hizli aksiyon</h4>
                    ${renderRawLeadPrimaryActions(rawLead)}
                </div>
                <div class="detail-block">
                    <h4>AI enrichment draft</h4>
                    ${renderRawLeadAIDraftPanel(rawLead, aiDrafts)}
                </div>
                <details class="detail-block simple-toggle" open>
                    <summary>Arastirma ozeti ve karar verici</summary>
                    <div class="detail-two-col toggle-body">
                        <div>
                            <h4>Arastirma notlari</h4>
                            <p class="detail-copy">${escapeHtml(rawLead.fit_reason || "Henuz fit nedeni yok.")}</p>
                            <p class="detail-copy">${escapeHtml(rawLead.recent_signal || "Guncel sinyal bekleniyor.")}</p>
                            <p class="detail-copy">Eksik veri: ${escapeHtml((rawLead.missing_fields || []).join(", ") || "yok")}</p>
                        </div>
                        <div>
                            <h4>Karar verici</h4>
                            <p class="detail-copy">Ad: ${escapeHtml(decisionMaker.name || "bulunmadi")}</p>
                            <p class="detail-copy">Rol: ${escapeHtml(decisionMaker.title || "belirtilmedi")}</p>
                            <p class="detail-copy">Email: ${escapeHtml(decisionMaker.email || "yok")}</p>
                            <p class="detail-copy">LinkedIn hint: ${escapeHtml(decisionMaker.linkedin_hint || "yok")}</p>
                        </div>
                    </div>
                </details>
                <details class="detail-block simple-toggle">
                    <summary>Timeline</summary>
                    <div class="toggle-body">
                        ${renderTimelineSection(timelineEntries)}
                    </div>
                </details>
                <details class="detail-block simple-toggle">
                    <summary>Duzenle ve not ekle</summary>
                    <div class="detail-two-col toggle-body">
                        <div>
                            <h4>Kaydi duzenle</h4>
                            ${renderRawLeadEditForm(rawLead)}
                        </div>
                        <div>
                            <h4>Not ekle</h4>
                            ${renderRawLeadNoteForm(rawLead)}
                        </div>
                    </div>
                </details>
                ${renderDetailState()}
            </div>
        `;
        return;
    }

    const lead = state.leads.find((item) => item.id === selected.id);

    if (!lead) {
        elements.detailPanel.innerHTML = "Secilen lead artik listede yok.";
        return;
    }

    const timelineEntries = state.detail.leadTimelineById[lead.id] || [];
    elements.detailPanel.innerHTML = `
        <div class="detail-card">
            <div class="detail-block">
                <p class="section-kicker">Lead #${lead.id}</p>
                <h3>${escapeHtml(lead.company_name)}</h3>
                <div class="badge-row">
                    ${renderBadge(lead.status)}
                    ${renderBadge(lead.crm_status)}
                    ${renderBadge(lead.outreach_status)}
                </div>
                <p class="detail-copy">${escapeHtml(lead.summary || lead.company_summary || "Lead detayi hazir.")}</p>
                <p class="detail-copy detail-hint">${escapeHtml(getLeadHint(lead))}</p>
            </div>
            <details class="detail-block simple-toggle" open>
                <summary>Lead ozeti</summary>
                <div class="detail-two-col toggle-body">
                    <div>
                        <h4>Temel bilgi</h4>
                        <p class="detail-copy">Fit nedeni: ${escapeHtml(lead.fit_reason || "yok")}</p>
                        <p class="detail-copy">Signal: ${escapeHtml(lead.recent_signal || "yok")}</p>
                        <p class="detail-copy">Eksik veri: ${escapeHtml((lead.missing_fields || []).join(", ") || "yok")}</p>
                        <p class="detail-copy">Owner: ${escapeHtml(lead.sales_owner || "atanmadi")}</p>
                    </div>
                    <div>
                        <h4>Karar verici</h4>
                        <p class="detail-copy">Ad: ${escapeHtml(lead.decision_maker?.name || "yok")}</p>
                        <p class="detail-copy">Rol: ${escapeHtml(lead.decision_maker?.title || "yok")}</p>
                        <p class="detail-copy">Email: ${escapeHtml(lead.decision_maker?.email || "yok")}</p>
                        <p class="detail-copy">LinkedIn hint: ${escapeHtml(lead.decision_maker?.linkedin_hint || "yok")}</p>
                    </div>
                </div>
            </details>
            <details class="detail-block simple-toggle">
                <summary>Mesajlar</summary>
                <div class="detail-two-col toggle-body">
                    <div>
                        <h4>Ilk mesaj</h4>
                        ${lead.first_message ? renderMessageBox(lead.first_message) : '<div class="empty-state">Henuz ilk mesaj taslagi yok.</div>'}
                    </div>
                    <div>
                        <h4>Follow-up</h4>
                        ${lead.follow_up_message ? renderMessageBox(lead.follow_up_message) : '<div class="empty-state">Henuz follow-up taslagi yok.</div>'}
                    </div>
                </div>
            </details>
            <details class="detail-block simple-toggle">
                <summary>Timeline</summary>
                <div class="toggle-body">
                    ${renderTimelineSection(timelineEntries)}
                </div>
            </details>
            <details class="detail-block simple-toggle">
                <summary>Duzenle ve not ekle</summary>
                <div class="detail-two-col toggle-body">
                    <div>
                        <h4>Lead duzenle</h4>
                        ${renderLeadEditForm(lead)}
                    </div>
                    <div>
                        <h4>Not ekle</h4>
                        ${renderLeadNoteForm(lead)}
                    </div>
                </div>
            </details>
            ${renderDetailState()}
        </div>
    `;
}

async function hydrateSelectedTimeline({ silent = false } = {}) {
    if (!state.selected) {
        state.detail.loading = false;
        state.detail.error = null;
        renderDetailPanel();
        return;
    }

    const selected = state.selected;
    const key = selected.kind === "raw" ? "rawTimelineById" : "leadTimelineById";
    const url = selected.kind === "raw"
        ? `/raw-leads/${selected.id}/timeline`
        : `/leads/${selected.id}/timeline`;

    state.detail.loading = true;
    state.detail.error = null;
    renderDetailPanel();

    try {
        const payload = await apiRequest(url);
        state.detail[key][selected.id] = payload.entries || [];
    } catch (error) {
        state.detail.error = error.message;
        if (!silent) {
            setStatus(error.message, "error");
        }
    } finally {
        state.detail.loading = false;
        renderDetailPanel();
    }
}

async function hydrateSelectedAIDrafts({ silent = false } = {}) {
    if (!state.selected || state.selected.kind !== "raw") {
        return;
    }

    try {
        const rawLeadId = state.selected.id;
        const historyMode = state.detail.rawDraftHistoryModeById[rawLeadId] || "active";
        const drafts = await apiRequest(
            `/ai/raw-leads/${rawLeadId}/drafts${historyMode === "all" ? "?include_archived=true" : ""}`
        );
        state.detail.rawDraftsById[rawLeadId] = drafts;

        if (drafts.length) {
            await hydrateAIDraftPreview(drafts[0].id, { silent: true });
        }

        const compareCandidates = drafts.slice(1);
        if (!compareCandidates.length) {
            delete state.detail.rawDraftComparisonById[rawLeadId];
            delete state.detail.rawDraftCompareSelectionById[rawLeadId];
            renderDetailPanel();
            return;
        }

        const selectedCompareId = state.detail.rawDraftCompareSelectionById[rawLeadId];
        const hasSelection = compareCandidates.some((draft) => draft.id === selectedCompareId);
        const compareDraftId = hasSelection ? selectedCompareId : compareCandidates[0].id;

        state.detail.rawDraftCompareSelectionById[rawLeadId] = compareDraftId;
        delete state.detail.rawDraftComparisonById[rawLeadId];
        await hydrateAIDraftComparison(drafts[0].id, compareDraftId, { rawLeadId, silent: true });
        renderDetailPanel();
    } catch (error) {
        if (!silent) {
            setStatus(error.message, "error");
        }
    }
}

async function hydrateSelectedOpenClawPreview({ silent = false } = {}) {
    if (!state.selected || state.selected.kind !== "raw") {
        return;
    }

    try {
        const rawLeadId = state.selected.id;
        const preview = await apiRequest(`/ai/raw-leads/${rawLeadId}/openclaw-preview`);
        state.detail.openclawPreviewById[rawLeadId] = preview;
        renderDetailPanel();
    } catch (error) {
        if (!silent) {
            setStatus(error.message, "error");
        }
    }
}

async function hydrateAIDraftPreview(draftId, { silent = false } = {}) {
    try {
        const preview = await apiRequest(`/ai/drafts/${draftId}/preview`);
        state.detail.rawDraftPreviewById[draftId] = preview;
        renderDetailPanel();
    } catch (error) {
        if (!silent) {
            setStatus(error.message, "error");
        }
    }
}

async function hydrateAIDraftComparison(baseDraftId, compareDraftId, { rawLeadId, silent = false } = {}) {
    if (!rawLeadId) {
        return;
    }

    try {
        const comparison = await apiRequest(`/ai/drafts/${baseDraftId}/compare/${compareDraftId}`);
        state.detail.rawDraftComparisonById[rawLeadId] = comparison;
        renderDetailPanel();
    } catch (error) {
        delete state.detail.rawDraftComparisonById[rawLeadId];
        if (!silent) {
            setStatus(error.message, "error");
        }
    }
}

function renderMessageBox(message) {
    return `
        <p class="detail-copy">Kanal: ${escapeHtml(message.channel || "email")} | Durum: ${escapeHtml(message.status || "draft")}</p>
        <p class="detail-copy">Konu: ${escapeHtml(message.subject || "yok")}</p>
        <div class="message-box">${escapeHtml(message.body || "")}</div>
    `;
}

function renderTimeline(entries) {
    if (!entries.length) {
        return '<div class="empty-state">Timeline henuz hazir degil.</div>';
    }

    return `
        <ol class="timeline-list">
            ${entries
                .map(
                    (entry) => `
                        <li class="timeline-item">
                            <div class="timeline-stamp">${escapeHtml(formatDate(entry.at))}</div>
                            <div>
                                <strong>${escapeHtml(entry.type || "activity")}</strong>
                                <p>${escapeHtml(entry.note || "")}</p>
                            </div>
                        </li>
                    `
                )
                .join("")}
        </ol>
    `;
}

function renderTimelineSection(entries) {
    const filteredEntries = filterTimelineEntries(entries);
    const typeOptions = renderTimelineTypeOptions(entries, state.detail.timelineType);

    return `
        <div class="timeline-toolbar">
            <label class="detail-field">
                <span>Tip</span>
                <select data-detail-filter="timeline-type">
                    ${typeOptions}
                </select>
            </label>
            <label class="detail-field timeline-search-field">
                <span>Timeline arama</span>
                <input
                    data-detail-filter="timeline-search"
                    type="text"
                    value="${escapeHtml(state.detail.timelineSearch)}"
                    placeholder="not veya aktivite ara"
                >
            </label>
        </div>
        <p class="timeline-meta">${escapeHtml(`${filteredEntries.length} kayit gosteriliyor`)}</p>
        ${renderTimeline(filteredEntries)}
    `;
}

function renderRawLeadEditForm(rawLead) {
    return `
        <form class="detail-form" data-detail-form="raw-update">
            <label class="detail-field">
                <span>Priority</span>
                <select name="priority">
                    ${renderPriorityOptions(rawLead.priority)}
                </select>
            </label>
            <label class="detail-field">
                <span>Confidence</span>
                <select name="confidence">
                    ${renderConfidenceOptions(rawLead.confidence)}
                </select>
            </label>
            <label class="detail-field detail-field-wide">
                <span>Company summary</span>
                <textarea name="company_summary" rows="3" placeholder="Sirket ozetini duzenle">${escapeHtml(rawLead.company_summary || "")}</textarea>
            </label>
            <label class="detail-field detail-field-wide">
                <span>Summary</span>
                <textarea name="summary" rows="3" placeholder="Kisa satis ozeti">${escapeHtml(rawLead.summary || "")}</textarea>
            </label>
            <label class="detail-field detail-field-wide">
                <span>Fit reason</span>
                <textarea name="fit_reason" rows="3" placeholder="Neden uygun lead?">${escapeHtml(rawLead.fit_reason || "")}</textarea>
            </label>
            <label class="detail-field detail-field-wide">
                <span>Review note</span>
                <textarea name="review_note" rows="3" placeholder="Review notu">${escapeHtml(rawLead.review_note || "")}</textarea>
            </label>
            <button class="primary-button detail-button" type="submit" ${!canWriteRawLeads() ? "disabled" : ""}>Raw lead guncelle</button>
        </form>
    `;
}

function renderRawLeadNoteForm(rawLead) {
    const notes = rawLead.personal_notes || [];

    return `
        <div class="detail-note-stack">
            <form class="detail-form" data-detail-form="raw-note">
                <label class="detail-field detail-field-wide">
                    <span>Yeni not</span>
                    <textarea name="note" rows="4" placeholder="Arastirma veya kalite notu ekle" required></textarea>
                </label>
                <button class="secondary-button detail-button" type="submit" ${!canWriteRawLeads() ? "disabled" : ""}>Not ekle</button>
            </form>
            <div class="detail-history">
                ${notes.length ? notes.map((note) => `<div class="history-item">${escapeHtml(note)}</div>`).join("") : '<div class="empty-state">Henuz not yok.</div>'}
            </div>
        </div>
    `;
}

function renderLeadEditForm(lead) {
    return `
        <form class="detail-form" data-detail-form="lead-update">
            <label class="detail-field">
                <span>Sales owner</span>
                <input name="sales_owner" type="text" value="${escapeHtml(lead.sales_owner || "")}" placeholder="owner-adi">
            </label>
            <label class="detail-field">
                <span>Priority</span>
                <select name="priority">
                    ${renderPriorityOptions(lead.priority)}
                </select>
            </label>
            <label class="detail-field">
                <span>Confidence</span>
                <select name="confidence">
                    ${renderConfidenceOptions(lead.confidence)}
                </select>
            </label>
            <label class="detail-field detail-field-wide">
                <span>Summary</span>
                <textarea name="summary" rows="3" placeholder="Lead ozeti">${escapeHtml(lead.summary || "")}</textarea>
            </label>
            <label class="detail-field detail-field-wide">
                <span>Fit reason</span>
                <textarea name="fit_reason" rows="3" placeholder="Lead fit nedeni">${escapeHtml(lead.fit_reason || "")}</textarea>
            </label>
            <button class="primary-button detail-button" type="submit" ${!canWriteLeads() ? "disabled" : ""}>Lead guncelle</button>
        </form>
    `;
}

function renderLeadNoteForm(lead) {
    const notes = (lead.activity_log || []).filter((item) => item.type === "user_note");

    return `
        <div class="detail-note-stack">
            <form class="detail-form" data-detail-form="lead-note">
                <label class="detail-field detail-field-wide">
                    <span>Yeni not</span>
                    <textarea name="note" rows="4" placeholder="Gorusme, owner veya CRM notu ekle" required></textarea>
                </label>
                <button class="secondary-button detail-button" type="submit" ${!canWriteLeads() ? "disabled" : ""}>Not ekle</button>
            </form>
            <div class="detail-history">
                ${notes.length
                    ? notes
                        .slice()
                        .reverse()
                        .map(
                            (item) => `
                                <div class="history-item">
                                    <strong>${escapeHtml(formatDate(item.at))}</strong>
                                    <p>${escapeHtml(item.note || "")}</p>
                                </div>
                            `
                        )
                        .join("")
                    : '<div class="empty-state">Henuz kullanici notu yok.</div>'}
            </div>
        </div>
    `;
}

function renderRawLeadAIDraftPanel(rawLead, drafts) {
    const historyMode = state.detail.rawDraftHistoryModeById[rawLead.id] || "active";
    const openclawPreview = state.detail.openclawPreviewById[rawLead.id] || null;
    const latestDraft = drafts[0] || null;
    const draftSummary = latestDraft
        ? extractDraftPayload(latestDraft)
        : null;
    const reviewMeta = latestDraft
        ? extractDraftReviewMeta(latestDraft)
        : null;
    const archiveMeta = latestDraft
        ? extractDraftArchiveMeta(latestDraft)
        : null;
    const preview = latestDraft
        ? state.detail.rawDraftPreviewById[latestDraft.id] || null
        : null;
    const compareSelection = state.detail.rawDraftCompareSelectionById[rawLead.id] || "";
    const comparison = state.detail.rawDraftComparisonById[rawLead.id] || null;
    const olderDrafts = drafts.slice(1);

    return `
        <div class="detail-note-stack">
            <form class="detail-form" data-detail-form="raw-ai-create">
                <p class="detail-copy">OpenClaw adapter sadece guvenli payload ile draft uretir. Kayit ancak manuel onayla degisir.</p>
                <button class="secondary-button detail-button" type="submit" ${!canWriteRawLeads() ? "disabled" : ""}>OpenClaw dry run</button>
            </form>
            ${
                openclawPreview
                    ? renderOpenClawSandbox(openclawPreview)
                    : '<div class="empty-state">OpenClaw sandbox yukleniyor...</div>'
            }
            <div class="history-item compare-toolbar">
                <strong>Draft history gorunumu</strong>
                <label class="detail-field">
                    <span>Liste modu</span>
                    <select data-detail-filter="draft-history-mode">
                        <option value="active" ${historyMode === "active" ? "selected" : ""}>aktif draftlar</option>
                        <option value="all" ${historyMode === "all" ? "selected" : ""}>tum history</option>
                    </select>
                </label>
                <p>${historyMode === "active" ? "Arsivlenen draftlar gizleniyor." : "Tum draft versiyonlari listeleniyor."}</p>
            </div>
            ${
                latestDraft
                    ? `
                        <div class="history-item">
                            <strong>Son draft #${escapeHtml(String(latestDraft.id))}</strong>
                            <p>Provider: ${escapeHtml(latestDraft.provider)} | Durum: ${escapeHtml(latestDraft.status)}</p>
                            <p>Summary: ${escapeHtml(draftSummary?.summary || "yok")}</p>
                            <p>Fit reason: ${escapeHtml(draftSummary?.fit_reason || "yok")}</p>
                            <p>Priority: ${escapeHtml(draftSummary?.priority || "yok")} | Confidence: ${escapeHtml(draftSummary?.confidence || "yok")}</p>
                            ${preview ? `<p>Degisecek alan: ${escapeHtml(String(preview.changed_fields_total))}</p>` : ""}
                            ${
                                reviewMeta
                                    ? `<p>Review: ${escapeHtml(reviewMeta.status || "-")} / ${escapeHtml(reviewMeta.actor_name || "-")} / ${escapeHtml(reviewMeta.note || "-")}</p>`
                                    : ""
                            }
                            ${
                                archiveMeta
                                    ? `<p>Archive: ${escapeHtml(archiveMeta.actor_name || "-")} / ${escapeHtml(archiveMeta.note || "-")}</p>`
                                    : ""
                            }
                            ${
                                extractDraftRestoreMeta(latestDraft)
                                    ? `<p>Restore: ${escapeHtml(extractDraftRestoreMeta(latestDraft).actor_name || "-")} / ${escapeHtml(extractDraftRestoreMeta(latestDraft).note || "-")} / ${escapeHtml(extractDraftRestoreMeta(latestDraft).restored_to || "-")}</p>`
                                    : ""
                            }
                        </div>
                        ${preview ? renderAIDraftPreview(preview) : '<div class="empty-state">Draft diff hazirlaniyor...</div>'}
                        ${
                            olderDrafts.length
                                ? `
                                    <div class="detail-history compare-history">
                                        <div class="history-item compare-toolbar">
                                            <strong>Draft history compare</strong>
                                            <label class="detail-field">
                                                <span>Eski draft sec</span>
                                                <select data-detail-filter="draft-compare-id">
                                                    ${renderDraftHistoryOptions(olderDrafts, compareSelection)}
                                                </select>
                                            </label>
                                            <p>Son draft her zaman baz alinir. Sectigin onceki draft ile alan farklari asagida gosterilir.</p>
                                        </div>
                                        ${
                                            comparison
                                                ? renderAIDraftComparison(comparison)
                                                : '<div class="empty-state">Karsilastirma hazirlaniyor...</div>'
                                        }
                                    </div>
                                `
                                : ""
                        }
                        ${renderDraftReviewActions(latestDraft)}
                        <form class="detail-form" data-detail-form="raw-ai-approve">
                            <input type="hidden" name="draft_id" value="${escapeHtml(String(latestDraft.id))}">
                            <button class="primary-button detail-button" type="submit" ${latestDraft.status !== "pending" || !canWriteRawLeads() ? "disabled" : ""}>Son draft'i uygula</button>
                        </form>
                        <form class="detail-form" data-detail-form="raw-ai-reject">
                            <input type="hidden" name="draft_id" value="${escapeHtml(String(latestDraft.id))}">
                            <label class="detail-field detail-field-wide">
                                <span>Reject notu</span>
                                <textarea name="note" rows="3" placeholder="Neden reddedildi?"></textarea>
                            </label>
                            <button class="tiny-button danger detail-button" type="submit" ${latestDraft.status !== "pending" || !canWriteRawLeads() ? "disabled" : ""}>Son draft'i reject et</button>
                        </form>
                        ${
                            olderDrafts.length
                                ? `<div class="detail-history">${olderDrafts
                                    .slice(0, 4)
                                    .map(
                                        (draft) => `
                                            <div class="history-item">
                                                <strong>Draft #${escapeHtml(String(draft.id))}</strong>
                                                <p>Durum: ${escapeHtml(draft.status)} | Olusturan: ${escapeHtml(draft.actor_name || "-")}</p>
                                                <p>Tarih: ${escapeHtml(formatDate(draft.created_at))}</p>
                                                ${
                                                    extractDraftArchiveMeta(draft)
                                                        ? `<p>Archive: ${escapeHtml(extractDraftArchiveMeta(draft).actor_name || "-")} / ${escapeHtml(extractDraftArchiveMeta(draft).note || "-")}</p>`
                                                        : ""
                                                }
                                                ${
                                                    extractDraftRestoreMeta(draft)
                                                        ? `<p>Restore: ${escapeHtml(extractDraftRestoreMeta(draft).actor_name || "-")} / ${escapeHtml(extractDraftRestoreMeta(draft).note || "-")} / ${escapeHtml(extractDraftRestoreMeta(draft).restored_to || "-")}</p>`
                                                        : ""
                                                }
                                                ${renderDraftReviewActions(draft, true)}
                                            </div>
                                        `
                                    )
                                    .join("")}</div>`
                                : ""
                        }
                    `
                    : `<div class="empty-state">${
                        historyMode === "active"
                            ? "Aktif AI draft yok. Gerekirse tum history moduna gec."
                            : "Bu raw lead icin henuz AI draft yok."
                    }</div>`
            }
        </div>
    `;
}

function renderOpenClawSandbox(preview) {
    const runtime = preview.runtime || {};
    const latestDraft = preview.latest_draft || null;

    return `
        <div class="detail-history">
            <div class="history-item sandbox-item">
                <strong>OpenClaw sandbox</strong>
                <p>Provider: ${escapeHtml(runtime.provider || "openclaw")} | Mode: ${escapeHtml(runtime.mode || "mock")} | Draft sayisi: ${escapeHtml(String(preview.drafts_total || 0))}</p>
                <p>Dry run: ${escapeHtml(runtime.dry_run_only ? "on" : "off")} | Gateway: ${escapeHtml(runtime.gateway_configured ? "configured" : "missing")} | Key: ${escapeHtml(runtime.api_key_configured ? "configured" : "missing")}</p>
                <p>${escapeHtml(runtime.recommended_next_step || "Bu panel gercek entegrasyon oncesi OpenClaw'a ne gidecegini gosterir.")}</p>
            </div>
            <div class="history-item sandbox-item">
                <strong>Safe request payload</strong>
                <pre class="json-preview">${escapeHtml(formatJsonPreview(preview.request_payload || {}))}</pre>
            </div>
            <div class="history-item sandbox-item">
                <strong>Latest adapter output</strong>
                ${
                    latestDraft
                        ? `
                            <p>Draft #${escapeHtml(String(latestDraft.id))} | Status: ${escapeHtml(latestDraft.status || "-")} | Provider: ${escapeHtml(latestDraft.provider || "-")}</p>
                            <pre class="json-preview">${escapeHtml(formatJsonPreview(latestDraft.response_payload || {}))}</pre>
                        `
                        : '<p>Henuz OpenClaw dry run sonucu yok. Once dry run butonunu kullan.</p>'
                }
            </div>
        </div>
    `;
}

function renderAIDraftPreview(preview) {
    const visibleChanges = (preview.changes || []).filter((item) => item.changed);

    if (!visibleChanges.length) {
        return '<div class="empty-state">Bu draft mevcut raw lead ile ayni gorunuyor.</div>';
    }

    return `
        <div class="detail-history">
            ${visibleChanges
                .map(
                    (change) => `
                        <div class="history-item diff-item">
                            <strong>${escapeHtml(change.label)}</strong>
                            <p><span class="diff-label">Current:</span> ${escapeHtml(formatPreviewValue(change.current_value))}</p>
                            <p><span class="diff-label">Draft:</span> ${escapeHtml(formatPreviewValue(change.draft_value))}</p>
                        </div>
                    `
                )
                .join("")}
        </div>
    `;
}

function renderAIDraftComparison(comparison) {
    const visibleChanges = (comparison.changes || []).filter((item) => item.changed);

    if (!visibleChanges.length) {
        return '<div class="empty-state">Secilen draft ile son draft ayni gorunuyor.</div>';
    }

    return `
        <div class="detail-history">
            <div class="history-item compare-summary">
                <strong>Latest draft #${escapeHtml(String(comparison.base_draft?.id || "-"))}</strong>
                <p>Durum: ${escapeHtml(comparison.base_draft?.status || "-")} | Tarih: ${escapeHtml(formatDate(comparison.base_draft?.created_at))}</p>
                <p>Karsilastirilan draft #${escapeHtml(String(comparison.compare_draft?.id || "-"))} | Durum: ${escapeHtml(comparison.compare_draft?.status || "-")}</p>
                <p>Farkli alan: ${escapeHtml(String(comparison.changed_fields_total || 0))}</p>
            </div>
            ${visibleChanges
                .map(
                    (change) => `
                        <div class="history-item diff-item">
                            <strong>${escapeHtml(change.label)}</strong>
                            <p><span class="diff-label">Latest:</span> ${escapeHtml(formatPreviewValue(change.base_value))}</p>
                            <p><span class="diff-label">Older:</span> ${escapeHtml(formatPreviewValue(change.compare_value))}</p>
                        </div>
                    `
                )
                .join("")}
        </div>
    `;
}

function renderDetailState() {
    if (state.detail.loading) {
        return '<div class="detail-alert">Timeline yukleniyor...</div>';
    }

    if (state.detail.error) {
        return `<div class="detail-alert error">${escapeHtml(state.detail.error)}</div>`;
    }

    return "";
}

async function submitRawLeadUpdate(form) {
    const rawLeadId = state.selected?.id;
    const payload = compactPayload({
        priority: form.elements.priority.value,
        confidence: form.elements.confidence.value,
        company_summary: form.elements.company_summary.value.trim(),
        summary: form.elements.summary.value.trim(),
        fit_reason: form.elements.fit_reason.value.trim(),
        review_note: form.elements.review_note.value.trim(),
    });

    if (!Object.keys(payload).length) {
        setStatus("Guncellenecek alan secilmedi.", "error");
        return;
    }

    setStatus("Raw lead guncelleniyor...", "pending");
    await apiRequest(`/raw-leads/${rawLeadId}`, {
        method: "PATCH",
        body: payload,
    });
    await refreshDashboard("Raw lead kaydi guncellendi.");
}

async function submitRawLeadResearch() {
    const rawLeadId = state.selected?.id;

    setStatus("Raw lead arastiriliyor...", "pending");
    await apiRequest(`/raw-leads/${rawLeadId}/research`, { method: "POST" });
    await refreshDashboard("Raw lead arastirma sonucu guncellendi.");
}

async function submitRawLeadReview(form) {
    const rawLeadId = state.selected?.id;
    const reviewAction = form.elements.review_action.value;
    const reviewerNote = form.elements.reviewer_note.value.trim();

    setStatus(`Raw lead ${reviewAction} ediliyor...`, "pending");
    await apiRequest(`/raw-leads/${rawLeadId}/review`, {
        method: "POST",
        body: {
            action: reviewAction,
            reviewer_note: reviewerNote || null,
        },
    });
    await refreshDashboard("Raw lead review karari kaydedildi.");
}

async function submitRawLeadNote(form) {
    const rawLeadId = state.selected?.id;
    const note = form.elements.note.value.trim();

    if (!note) {
        setStatus("Not alani bos olamaz.", "error");
        return;
    }

    setStatus("Raw lead notu kaydediliyor...", "pending");
    await apiRequest(`/raw-leads/${rawLeadId}/notes`, {
        method: "POST",
        body: { note },
    });
    await refreshDashboard("Raw lead notu eklendi.");
}

async function submitLeadUpdate(form) {
    const leadId = state.selected?.id;
    const payload = compactPayload({
        sales_owner: form.elements.sales_owner.value.trim(),
        priority: form.elements.priority.value,
        confidence: form.elements.confidence.value,
        summary: form.elements.summary.value.trim(),
        fit_reason: form.elements.fit_reason.value.trim(),
    });

    if (!Object.keys(payload).length) {
        setStatus("Guncellenecek alan secilmedi.", "error");
        return;
    }

    setStatus("Lead kaydi guncelleniyor...", "pending");
    await apiRequest(`/leads/${leadId}`, {
        method: "PATCH",
        body: payload,
    });
    await refreshDashboard("Lead kaydi guncellendi.");
}

async function submitLeadNote(form) {
    const leadId = state.selected?.id;
    const note = form.elements.note.value.trim();

    if (!note) {
        setStatus("Not alani bos olamaz.", "error");
        return;
    }

    setStatus("Lead notu kaydediliyor...", "pending");
    await apiRequest(`/leads/${leadId}/notes`, {
        method: "POST",
        body: { note },
    });
    await refreshDashboard("Lead notu eklendi.");
}

async function submitRawLeadAIDraft() {
    const rawLeadId = state.selected?.id;

    setStatus("OpenClaw dry run calisiyor...", "pending");
    await apiRequest(`/ai/raw-leads/${rawLeadId}/enrichment-draft`, {
        method: "POST",
    });
    await refreshDashboard("OpenClaw dry run sonucu alindi.");
}

async function submitRawLeadAIApproval(form) {
    const draftId = form.elements.draft_id.value;

    setStatus("AI draft onayla uygulanıyor...", "pending");
    await apiRequest(`/ai/drafts/${draftId}/approve`, {
        method: "POST",
    });
    await refreshDashboard("AI draft raw lead kaydina uygulandi.");
}

async function submitRawLeadAIReject(form) {
    const draftId = form.elements.draft_id.value;
    const note = form.elements.note.value.trim();

    setStatus("AI draft reject ediliyor...", "pending");
    await apiRequest(`/ai/drafts/${draftId}/reject`, {
        method: "POST",
        body: { note: note || null },
    });
    await refreshDashboard("AI draft reject edildi.");
}

async function submitRawLeadAIArchive(form) {
    const draftId = form.elements.draft_id.value;
    const note = form.elements.note ? form.elements.note.value.trim() : "";

    setStatus("AI draft arsivleniyor...", "pending");
    await apiRequest(`/ai/drafts/${draftId}/archive`, {
        method: "POST",
        body: { note: note || null },
    });
    await refreshDashboard("AI draft history'den arsivlendi.");
}

async function submitRawLeadAIRestore(form) {
    const draftId = form.elements.draft_id.value;
    const note = form.elements.note ? form.elements.note.value.trim() : "";

    setStatus("AI draft arsivden geri aliniyor...", "pending");
    await apiRequest(`/ai/drafts/${draftId}/restore`, {
        method: "POST",
        body: { note: note || null },
    });
    await refreshDashboard("AI draft tekrar aktif history'ye alindi.");
}

function renderMetaItem(label, value) {
    return `
        <div class="meta-item">
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value || "-")}</dd>
        </div>
    `;
}

function renderBadge(value) {
    const normalized = String(value || "").toLowerCase();
    let modifier = "badge-accent";

    if (normalized.includes("reject") || normalized.includes("negative") || normalized.includes("low")) {
        modifier = "badge-danger";
    } else if (
        normalized.includes("pending") ||
        normalized.includes("hold") ||
        normalized.includes("draft") ||
        normalized.includes("follow_up")
    ) {
        modifier = "badge-warm";
    }

    return `<span class="badge ${modifier}">${escapeHtml(translateUiValue(value || "-"))}</span>`;
}

function formatCounter(counterObject = {}) {
    const entries = Object.entries(counterObject || {});

    if (!entries.length) {
        return "Henuz veri yok";
    }

    return entries
        .map(([key, value]) => `${key}: ${value}`)
        .join(" | ");
}

function formatRoles(roles) {
    if (!roles.length) {
        return "Rol bilgisi yok";
    }

    return roles
        .map((item) => `${item.role}: ${(item.permissions || []).join(", ")}`)
        .join(" | ");
}

function formatOpenClawSetup(ai) {
    if (!ai || !Object.keys(ai).length) {
        return "OpenClaw bilgisi yok";
    }

    const warningText = (ai.warnings || []).length ? ` | uyari: ${(ai.warnings || []).join(" / ")}` : "";
    const modelProvider = ai.model_provider || "none";
    const modelName = ai.model_name || "-";

    return [
        `durum: ${translateUiValue(ai.setup_state || "unknown")}`,
        `model: ${translateUiValue(modelProvider)}/${modelName}`,
        `deneme: ${ai.dry_run_only ? "acik" : "kapali"}`,
        `ag gecidi: ${ai.gateway_configured ? "hazir" : "eksik"}`,
        `tarayici: ${ai.safety?.browser_automation_enabled ? "acik" : "kapali"}`,
    ].join(" | ") + warningText;
}

function normalizeSelection() {
    if (!state.selected) {
        return;
    }

    if (state.selected.kind === "raw") {
        const exists = state.rawLeads.some((item) => item.id === state.selected.id);
        if (!exists) {
            state.selected = null;
            state.detail.error = null;
            state.detail.loading = false;
        }
    }

    if (state.selected?.kind === "lead") {
        const exists = state.leads.some((item) => item.id === state.selected.id);
        if (!exists) {
            state.selected = null;
            state.detail.error = null;
            state.detail.loading = false;
        }
    }
}

function formatConnection(connection) {
    if (!connection || !Object.keys(connection).length) {
        return "Baglanti bilgisi yok";
    }

    if (connection.host) {
        return `${connection.user}@${connection.host}:${connection.port}/${connection.database}`;
    }

    if (connection.database) {
        return connection.database;
    }

    return "Baglanti bilgisi yok";
}

function toQueryString(params) {
    const searchParams = new URLSearchParams();

    Object.entries(params).forEach(([key, value]) => {
        if (value) {
            searchParams.set(key, value);
        }
    });

    const query = searchParams.toString();
    return query ? `?${query}` : "";
}

function setStatus(message, tone) {
    elements.statusBanner.textContent = message;
    elements.statusBanner.className = `status-banner status-${tone}`;
}

function renderEmptyState(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function syncActorFromInputs() {
    if (!elements.actorRoleSelect || !elements.actorNameInput) {
        return;
    }

    state.actor.role = elements.actorRoleSelect.value || "admin";
    state.actor.name = elements.actorNameInput.value.trim() || "demo-admin";
    window.localStorage.setItem("openclawpilot-actor", JSON.stringify(state.actor));
}

function syncFiltersFromInputs() {
    state.filters.rawStatus = elements.rawStatusFilter.value;
    state.filters.rawResearchStatus = elements.rawResearchStatusFilter.value;
    state.filters.rawPriority = elements.rawPriorityFilter.value;
    state.filters.rawReliability = elements.rawReliabilityFilter.value;
    state.filters.rawSearch = elements.rawSearchFilter.value.trim();
    state.filters.leadStatus = elements.leadStatusFilter.value;
    state.filters.leadCrmStatus = elements.leadCrmStatusFilter.value;
    state.filters.leadOutreachStatus = elements.leadOutreachStatusFilter.value;
    state.filters.leadPriority = elements.leadPriorityFilter.value;
    state.filters.leadOwner = elements.leadOwnerFilter.value.trim();
    state.filters.leadSearch = elements.leadSearchFilter.value.trim();
}

function setSelectedRecord(selection) {
    const selectionChanged =
        state.selected?.kind !== selection.kind || state.selected?.id !== selection.id;

    state.selected = selection;

    if (selectionChanged) {
        state.detail.timelineType = "";
        state.detail.timelineSearch = "";
        state.detail.error = null;
    }
}

function getDetailFilterValue(filterName) {
    const control = elements.detailPanel.querySelector(`[data-detail-filter="${filterName}"]`);
    return control ? control.value.trim() : "";
}

function filterTimelineEntries(entries) {
    return entries.filter((entry) => {
        const matchesType = !state.detail.timelineType || entry.type === state.detail.timelineType;
        const haystack = `${entry.type || ""} ${entry.note || ""}`.toLowerCase();
        const matchesSearch =
            !state.detail.timelineSearch || haystack.includes(state.detail.timelineSearch.toLowerCase());

        return matchesType && matchesSearch;
    });
}

function renderTimelineTypeOptions(entries, selectedType) {
    const types = [...new Set(entries.map((entry) => entry.type).filter(Boolean))];
    const options = ['<option value="">hepsi</option>'];

    types.forEach((type) => {
        options.push(
            `<option value="${escapeHtml(type)}" ${selectedType === type ? "selected" : ""}>${escapeHtml(type)}</option>`
        );
    });

    return options.join("");
}

function compactPayload(payload) {
    return Object.fromEntries(
        Object.entries(payload).filter(([, value]) => typeof value === "string" ? value !== "" : value != null)
    );
}

function renderPriorityOptions(selectedValue) {
    return renderSelectOptions(["high", "medium", "low"], selectedValue, "sec");
}

function renderConfidenceOptions(selectedValue) {
    return renderSelectOptions(["high", "medium", "low"], selectedValue, "sec");
}

function renderSelectOptions(values, selectedValue, emptyLabel) {
    const options = [`<option value="">${escapeHtml(emptyLabel)}</option>`];

    values.forEach((value) => {
        options.push(
            `<option value="${escapeHtml(value)}" ${selectedValue === value ? "selected" : ""}>${escapeHtml(value)}</option>`
        );
    });

    return options.join("");
}

function renderDraftHistoryOptions(drafts, selectedDraftId) {
    return drafts
        .map((draft) => {
            const label = `#${draft.id} / ${draft.status} / ${formatDate(draft.created_at)}`;
            return `<option value="${escapeHtml(String(draft.id))}" ${Number(selectedDraftId) === draft.id ? "selected" : ""}>${escapeHtml(label)}</option>`;
        })
        .join("");
}

function extractDraftPayload(draft) {
    const responsePayload = draft?.response_payload || {};
    return responsePayload.draft || responsePayload;
}

function extractDraftReviewMeta(draft) {
    return draft?.response_payload?.meta?.review || null;
}

function extractDraftArchiveMeta(draft) {
    return draft?.response_payload?.meta?.archive || null;
}

function extractDraftRestoreMeta(draft) {
    return draft?.response_payload?.meta?.restore || null;
}

function renderDraftReviewActions(draft, compact = false) {
    if (draft.status === "archived") {
        return renderDraftRestoreAction(draft, compact);
    }

    return renderDraftArchiveAction(draft, compact);
}

function renderDraftArchiveAction(draft, compact = false) {
    if (draft.status === "pending" || draft.status === "archived") {
        return "";
    }

    return `
        <form class="detail-form ${compact ? "detail-form-inline" : ""}" data-detail-form="raw-ai-archive">
            <input type="hidden" name="draft_id" value="${escapeHtml(String(draft.id))}">
            <label class="detail-field detail-field-wide">
                <span>Archive notu</span>
                <textarea name="note" rows="${compact ? "2" : "3"}" placeholder="Bu draft neden arsive gidiyor?"></textarea>
            </label>
            <button class="tiny-button detail-button" type="submit" ${!canWriteRawLeads() ? "disabled" : ""}>Draft'i arsivle</button>
        </form>
    `;
}

function renderDraftRestoreAction(draft, compact = false) {
    if (draft.status !== "archived") {
        return "";
    }

    return `
        <form class="detail-form ${compact ? "detail-form-inline" : ""}" data-detail-form="raw-ai-restore">
            <input type="hidden" name="draft_id" value="${escapeHtml(String(draft.id))}">
            <label class="detail-field detail-field-wide">
                <span>Restore notu</span>
                <textarea name="note" rows="${compact ? "2" : "3"}" placeholder="Bu draft neden geri aliniyor?"></textarea>
            </label>
            <button class="tiny-button accent detail-button" type="submit" ${!canWriteRawLeads() ? "disabled" : ""}>Draft'i geri al</button>
        </form>
    `;
}

function formatPreviewValue(value) {
    if (Array.isArray(value)) {
        return value.length ? value.join(", ") : "yok";
    }

    if (value && typeof value === "object") {
        return Object.entries(value)
            .map(([key, nestedValue]) => `${key}: ${nestedValue || "-"}`)
            .join(" | ");
    }

    return value || "yok";
}

function formatJsonPreview(value) {
    try {
        return JSON.stringify(value, null, 2);
    } catch (error) {
        return String(value ?? "");
    }
}

function formatDate(value) {
    if (!value) {
        return "zaman yok";
    }

    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value;
    }

    return parsed.toLocaleString("tr-TR", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function getRawLeadHint(rawLead) {
    if (rawLead.research_status !== "completed") {
        return "Siradaki adim: research tamamla.";
    }

    if (rawLead.status === "needs_review" || rawLead.status === "needs_revision" || rawLead.status === "on_hold") {
        return "Siradaki adim: review karari ver.";
    }

    if (rawLead.status === "approved") {
        return "Bu kayit lead pipeline'ina tasindi.";
    }

    if (rawLead.status === "rejected") {
        return "Akis bu kayitta kapandi.";
    }

    return "Kayit izleniyor.";
}

function getLeadHint(lead) {
    if (lead.status === "meeting_requested") {
        return "Lead olumlu yanit verdi; siradaki adim gorusme planlamak.";
    }

    if (lead.status === "closed_negative") {
        return "Lead olumsuz kapanmis durumda; outreach devam etmez.";
    }

    if (!lead.sales_owner) {
        return "Siradaki adim: owner ata ve CRM sync yap.";
    }

    if (lead.crm_status !== "synced") {
        return "Siradaki adim: lead'i CRM'e aktar.";
    }

    if (!lead.first_message) {
        return "Siradaki adim: ilk mesaj taslagi olustur.";
    }

    if (lead.first_message.status === "draft") {
        return "Siradaki adim: ilk mesaj taslagini onayla.";
    }

    if (lead.first_message.status === "approved") {
        return "Siradaki adim: ilk mesaji gonderildi olarak isaretle.";
    }

    if (lead.outreach_status === "awaiting_reply") {
        return "Musteri yaniti bekleniyor; gerekirse follow-up acabilirsin.";
    }

    if (lead.outreach_status === "follow_up_due") {
        return "Siradaki adim: follow-up taslagi olustur.";
    }

    if (lead.follow_up_message?.status === "draft") {
        return "Siradaki adim: follow-up taslagini onayla.";
    }

    if (lead.follow_up_message?.status === "approved") {
        return "Siradaki adim: follow-up mesajini gonderildi olarak isaretle.";
    }

    if (lead.outreach_status === "follow_up_sent") {
        return "Takip mesaji gonderildi; yanit kaydini bekliyor.";
    }

    return "Lead akis icinde ilerliyor.";
}

function canManageIntake() {
    return ["reviewer", "admin"].includes(state.actor.role);
}

function canWriteRawLeads() {
    return ["reviewer", "admin"].includes(state.actor.role);
}

function canWriteLeads() {
    return ["sales", "admin"].includes(state.actor.role);
}

function loadActorPreferences() {
    return {
        role: "admin",
        name: "panel",
    };
}

function translateUiValue(value) {
    const text = String(value ?? "");
    const lookup = {
        admin: "yonetici",
        reviewer: "inceleyen",
        sales: "satis",
        viewer: "goruntuleyici",
        postgres: "postgres",
        sqlite: "sqlite",
        mock: "deneme",
        sandbox: "sandbox",
        gateway: "ag gecidi",
        mock_ready: "deneme hazir",
        sandbox_ready: "sandbox hazir",
        ollama_config_needed: "ollama ayari eksik",
        ollama_sandbox_ready: "ollama sandbox hazir",
        configured_waiting_live: "hazir, canli kapali",
        config_needed: "ayar gerekli",
        unknown: "bilinmiyor",
        new: "yeni",
        needs_review: "inceleme bekliyor",
        approved: "onayli",
        on_hold: "beklemede",
        needs_revision: "revize gerekli",
        rejected: "reddedildi",
        pending: "bekliyor",
        completed: "tamamlandi",
        high: "yuksek",
        medium: "orta",
        low: "dusuk",
        sales_ready: "satisa hazir",
        draft_ready: "taslak hazir",
        ready_to_send: "gonderime hazir",
        awaiting_reply: "yanit bekleniyor",
        follow_up_draft_ready: "takip taslagi hazir",
        follow_up_sent: "takip gonderildi",
        reply_received: "yanit alindi",
        meeting_requested: "toplanti istendi",
        follow_up_due: "takip zamani",
        closed_negative: "olumsuz kapandi",
        synced: "aktarildi",
        not_started: "baslamadi",
        approved_to_send: "gonderime onayli",
        email: "e-posta",
        linkedin: "linkedin",
    };

    return lookup[text.toLowerCase()] || text;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
