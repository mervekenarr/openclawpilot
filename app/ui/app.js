const state = {
    keywords: [],
    rawLeads: [],
    leads: [],
    summary: null,
    selected: null,
};

const elements = {};

document.addEventListener("DOMContentLoaded", () => {
    assignElements();
    bindEvents();
    refreshDashboard("Dashboard hazirlandi.");
});

function assignElements() {
    elements.intakeForm = document.getElementById("intakeForm");
    elements.refreshButton = document.getElementById("refreshButton");
    elements.statusBanner = document.getElementById("statusBanner");
    elements.keywordRail = document.getElementById("keywordRail");
    elements.summaryGrid = document.getElementById("summaryGrid");
    elements.rawLeadList = document.getElementById("rawLeadList");
    elements.leadList = document.getElementById("leadList");
    elements.detailPanel = document.getElementById("detailPanel");
}

function bindEvents() {
    elements.intakeForm.addEventListener("submit", handleIntakeSubmit);
    elements.refreshButton.addEventListener("click", () => refreshDashboard("Veriler yenilendi."));
    elements.rawLeadList.addEventListener("click", handleRawLeadClick);
    elements.leadList.addEventListener("click", handleLeadClick);
}

async function refreshDashboard(successMessage) {
    setStatus("Veriler yukleniyor...", "pending");

    try {
        const [keywords, rawLeads, leads, summary] = await Promise.all([
            apiRequest("/keywords"),
            apiRequest("/raw-leads"),
            apiRequest("/leads"),
            apiRequest("/pipeline/summary"),
        ]);

        state.keywords = keywords;
        state.rawLeads = rawLeads;
        state.leads = leads;
        state.summary = summary;

        normalizeSelection();
        renderDashboard();
        setStatus(successMessage || "Dashboard guncellendi.", "success");
    } catch (error) {
        setStatus(error.message, "error");
    }
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
    state.selected = { kind: "raw", id: rawLeadId };
    renderDetailPanel();

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
    state.selected = { kind: "lead", id: leadId };
    renderDetailPanel();

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

async function apiRequest(url, options = {}) {
    const requestOptions = {
        method: options.method || "GET",
        headers: {
            "Accept": "application/json",
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
    renderKeywords();
    renderSummary();
    renderRawLeads();
    renderLeads();
    renderDetailPanel();
}

function renderKeywords() {
    if (!state.keywords.length) {
        elements.keywordRail.innerHTML = '<span class="keyword-pill empty">Henuz keyword kaydi yok.</span>';
        return;
    }

    elements.keywordRail.innerHTML = state.keywords
        .map((keyword) => `<span class="keyword-pill">${escapeHtml(keyword.keyword)}</span>`)
        .join("");
}

function renderSummary() {
    const summary = state.summary || {};

    const cards = [
        {
            label: "Keyword",
            value: summary.keywords_total || 0,
            meta: `${(state.keywords || []).slice(-3).map((item) => item.keyword).join(" / ") || "Henuz tanim yok"}`,
        },
        {
            label: "Raw leads",
            value: summary.raw_leads_total || 0,
            meta: formatCounter(summary.raw_lead_status),
        },
        {
            label: "Approved leads",
            value: summary.approved_leads_total || 0,
            meta: formatCounter(summary.lead_status),
        },
        {
            label: "Outreach / CRM",
            value: Object.keys(summary.outreach_status || {}).length,
            meta: `${formatCounter(summary.outreach_status)} | ${formatCounter(summary.crm_status)}`,
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
        elements.rawLeadList.innerHTML = renderEmptyState("Keyword girildiginde mock raw leadler burada akacak.");
        return;
    }

    elements.rawLeadList.innerHTML = state.rawLeads
        .map((rawLead) => {
            const isSelected = state.selected?.kind === "raw" && state.selected.id === rawLead.id;
            const reviewReady = ["needs_review", "needs_revision", "on_hold"].includes(rawLead.status);
            const researchDone = rawLead.research_status === "completed";
            const decisionMaker = rawLead.decision_maker || {};

            return `
                <article class="lead-card ${isSelected ? "is-selected" : ""}" data-raw-id="${rawLead.id}">
                    <div class="card-top">
                        <div>
                            <p class="card-kicker">Raw lead #${rawLead.id}</p>
                            <h3>${escapeHtml(rawLead.company_name)}</h3>
                        </div>
                        <div class="badge-row">
                            ${renderBadge(rawLead.status)}
                            ${renderBadge(rawLead.research_status)}
                            ${rawLead.priority ? renderBadge(rawLead.priority) : ""}
                        </div>
                    </div>
                    <p class="card-copy">${escapeHtml(rawLead.company_summary || rawLead.summary || "Arastirma bekliyor.")}</p>
                    <dl class="meta-grid">
                        ${renderMetaItem("Keyword", rawLead.keyword)}
                        ${renderMetaItem("Sektor", rawLead.sector)}
                        ${renderMetaItem("Kaynak", rawLead.source)}
                        ${renderMetaItem("Karar verici", decisionMaker.name || "Henuz bulunmadi")}
                    </dl>
                    <div class="action-stack">
                        <div class="action-row">
                            <button class="tiny-button accent" data-action="research" ${researchDone ? "disabled" : ""}>Research yap</button>
                            <button class="tiny-button accent" data-action="review-approve" ${!reviewReady ? "disabled" : ""}>Approve</button>
                            <button class="tiny-button warm" data-action="review-hold" ${!reviewReady ? "disabled" : ""}>Beklet</button>
                            <button class="tiny-button" data-action="review-revise" ${!reviewReady ? "disabled" : ""}>Revize iste</button>
                            <button class="tiny-button danger" data-action="review-reject" ${!reviewReady ? "disabled" : ""}>Reject</button>
                        </div>
                        <p class="mini-note">Eksik veri: ${escapeHtml((rawLead.missing_fields || []).join(", ") || "yok")}</p>
                    </div>
                </article>
            `;
        })
        .join("");
}

function renderLeads() {
    if (!state.leads.length) {
        elements.leadList.innerHTML = renderEmptyState("Approve edilen leadler burada CRM ve outreach akisina girer.");
        return;
    }

    elements.leadList.innerHTML = state.leads
        .map((lead) => {
            const isSelected = state.selected?.kind === "lead" && state.selected.id === lead.id;
            const firstMessage = lead.first_message || null;
            const followUpMessage = lead.follow_up_message || null;
            const canRecordReply = ["awaiting_reply", "follow_up_sent"].includes(lead.outreach_status);

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
                        ${renderMetaItem("Confidence", lead.confidence)}
                        ${renderMetaItem("Owner", lead.sales_owner || "atanmadi")}
                    </dl>
                    <div class="action-stack">
                        <div class="mini-control">
                            <span>CRM owner</span>
                            <div class="action-row">
                                <input data-role="owner" type="text" value="${escapeHtml(lead.sales_owner || "")}" placeholder="demo-user">
                                <button class="tiny-button accent" data-action="crm-sync">CRM sync</button>
                            </div>
                        </div>
                        <div class="mini-control">
                            <span>Ilk temas kanali</span>
                            <div class="action-row">
                                <select data-role="channel">
                                    <option value="email" ${firstMessage?.channel === "email" ? "selected" : ""}>email</option>
                                    <option value="linkedin" ${firstMessage?.channel === "linkedin" ? "selected" : ""}>linkedin</option>
                                </select>
                                <button class="tiny-button accent" data-action="draft-first-message" ${lead.crm_status !== "synced" ? "disabled" : ""}>Draft first message</button>
                                <button class="tiny-button" data-action="approve-first-message" ${firstMessage?.status !== "draft" ? "disabled" : ""}>Approve draft</button>
                                <button class="tiny-button warm" data-action="mark-first-message-sent" ${firstMessage?.status !== "approved" ? "disabled" : ""}>Mark sent</button>
                            </div>
                        </div>
                        <div class="mini-control">
                            <span>Follow-up dongusu</span>
                            <div class="action-row">
                                <button class="tiny-button accent" data-action="draft-follow-up" ${lead.outreach_status !== "awaiting_reply" ? "disabled" : ""}>Draft follow-up</button>
                                <button class="tiny-button" data-action="approve-follow-up" ${followUpMessage?.status !== "draft" ? "disabled" : ""}>Approve follow-up</button>
                                <button class="tiny-button warm" data-action="mark-follow-up-sent" ${followUpMessage?.status !== "approved" ? "disabled" : ""}>Mark follow-up sent</button>
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
                                <button class="tiny-button accent" data-action="record-reply" ${!canRecordReply ? "disabled" : ""}>Record reply</button>
                            </div>
                        </div>
                    </div>
                </article>
            `;
        })
        .join("");
}

function renderDetailPanel() {
    const selected = state.selected;

    if (!selected) {
        elements.detailPanel.innerHTML = "Henuz bir kayit secilmedi.";
        return;
    }

    if (selected.kind === "raw") {
        const rawLead = state.rawLeads.find((item) => item.id === selected.id);

        if (!rawLead) {
            elements.detailPanel.innerHTML = "Secilen raw lead artik listede yok.";
            return;
        }

        const decisionMaker = rawLead.decision_maker || {};
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
                </div>
                <div class="detail-two-col">
                    <div class="detail-block">
                        <h4>Arastirma notlari</h4>
                        <p class="detail-copy">${escapeHtml(rawLead.fit_reason || "Henuz fit nedeni yok.")}</p>
                        <p class="detail-copy">${escapeHtml(rawLead.recent_signal || "Guncel sinyal bekleniyor.")}</p>
                        <p class="detail-copy">Eksik veri: ${escapeHtml((rawLead.missing_fields || []).join(", ") || "yok")}</p>
                    </div>
                    <div class="detail-block">
                        <h4>Karar verici</h4>
                        <p class="detail-copy">Ad: ${escapeHtml(decisionMaker.name || "bulunmadi")}</p>
                        <p class="detail-copy">Rol: ${escapeHtml(decisionMaker.title || "belirtilmedi")}</p>
                        <p class="detail-copy">Email: ${escapeHtml(decisionMaker.email || "yok")}</p>
                        <p class="detail-copy">LinkedIn hint: ${escapeHtml(decisionMaker.linkedin_hint || "yok")}</p>
                    </div>
                </div>
            </div>
        `;
        return;
    }

    const lead = state.leads.find((item) => item.id === selected.id);

    if (!lead) {
        elements.detailPanel.innerHTML = "Secilen lead artik listede yok.";
        return;
    }

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
            </div>
            <div class="detail-two-col">
                <div class="detail-block">
                    <h4>Lead ozeti</h4>
                    <p class="detail-copy">Fit nedeni: ${escapeHtml(lead.fit_reason || "yok")}</p>
                    <p class="detail-copy">Signal: ${escapeHtml(lead.recent_signal || "yok")}</p>
                    <p class="detail-copy">Eksik veri: ${escapeHtml((lead.missing_fields || []).join(", ") || "yok")}</p>
                    <p class="detail-copy">Owner: ${escapeHtml(lead.sales_owner || "atanmadi")}</p>
                </div>
                <div class="detail-block">
                    <h4>Karar verici</h4>
                    <p class="detail-copy">Ad: ${escapeHtml(lead.decision_maker?.name || "yok")}</p>
                    <p class="detail-copy">Rol: ${escapeHtml(lead.decision_maker?.title || "yok")}</p>
                    <p class="detail-copy">Email: ${escapeHtml(lead.decision_maker?.email || "yok")}</p>
                    <p class="detail-copy">LinkedIn hint: ${escapeHtml(lead.decision_maker?.linkedin_hint || "yok")}</p>
                </div>
            </div>
            <div class="detail-two-col">
                <div class="detail-block">
                    <h4>Ilk mesaj</h4>
                    ${lead.first_message ? renderMessageBox(lead.first_message) : '<div class="empty-state">Henuz ilk mesaj taslagi yok.</div>'}
                </div>
                <div class="detail-block">
                    <h4>Follow-up</h4>
                    ${lead.follow_up_message ? renderMessageBox(lead.follow_up_message) : '<div class="empty-state">Henuz follow-up taslagi yok.</div>'}
                </div>
            </div>
            <div class="detail-block">
                <h4>Activity log</h4>
                ${
                    (lead.activity_log || []).length
                        ? `<ol class="activity-list">${lead.activity_log
                              .map(
                                  (item) => `
                                    <li>
                                        <strong>${escapeHtml(item.type)}</strong>:
                                        ${escapeHtml(item.note || "")}
                                    </li>
                                `
                              )
                              .join("")}</ol>`
                        : '<div class="empty-state">Henuz aktivite kaydi yok.</div>'
                }
            </div>
        </div>
    `;
}

function renderMessageBox(message) {
    return `
        <p class="detail-copy">Kanal: ${escapeHtml(message.channel || "email")} | Durum: ${escapeHtml(message.status || "draft")}</p>
        <p class="detail-copy">Konu: ${escapeHtml(message.subject || "yok")}</p>
        <div class="message-box">${escapeHtml(message.body || "")}</div>
    `;
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

    return `<span class="badge ${modifier}">${escapeHtml(value || "-")}</span>`;
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

function normalizeSelection() {
    if (!state.selected) {
        return;
    }

    if (state.selected.kind === "raw") {
        const exists = state.rawLeads.some((item) => item.id === state.selected.id);
        if (!exists) {
            state.selected = null;
        }
    }

    if (state.selected?.kind === "lead") {
        const exists = state.leads.some((item) => item.id === state.selected.id);
        if (!exists) {
            state.selected = null;
        }
    }
}

function setStatus(message, tone) {
    elements.statusBanner.textContent = message;
    elements.statusBanner.className = `status-banner status-${tone}`;
}

function renderEmptyState(message) {
    return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}
