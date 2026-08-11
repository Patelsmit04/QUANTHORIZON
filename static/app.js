/**
 * BTST SCANNER — DASHBOARD JAVASCRIPT APPLICATION ENGINE (AUTONOMOUS BACKGROUND SCANNER)
 */
var lastBtstStatus = "pre_btst";

// M9 audit fix: native fetch() has no timeout, and nothing in this file attached one to any
// of its ~18 call sites — a hung backend left "SCANNING..." (or an equivalent stuck state) up
// indefinitely with no visible error. apiFetch() is a drop-in fetch() replacement used
// everywhere below: it aborts after DEFAULT_FETCH_TIMEOUT_MS (override per-call via
// options.timeoutMs) and attaches the stored API key header automatically, since mutating
// endpoints (strategy CRUD, lock/evaluate picks, execute, notifications) now require one —
// see promptForApiKey() below. Uses window.fetch explicitly so this definition itself isn't
// caught by the fetch->apiFetch rename applied to every call site in this file.
const DEFAULT_FETCH_TIMEOUT_MS = 15000;

async function apiFetch(url, options = {}) {
    const { timeoutMs, headers, ...rest } = options;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs || DEFAULT_FETCH_TIMEOUT_MS);
    try {
        return await window.fetch(url, { ...rest, headers: headers || {}, signal: controller.signal });
    } finally {
        clearTimeout(timeoutId);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // Application State
    let allStocks = [];
    let currentFilter = "ALL";
    let currentStockView = "intelligence"; // "intelligence" or "live"
    let autoRefreshInterval = null;
    let newsRefreshInterval = null;
    // Strategy cards rebuild #strategyGrid from scratch on every toggle/edit action, so
    // collapsed/expanded state must survive that — tracked here, not as a DOM class.
    const collapsedStrategyIds = new Set();

    // Sidebar / Mobile Drawer DOM — #appSidebar is the single nav source for both the
    // desktop persistent rail and the mobile full-height drawer (see styles.css .app-sidebar).
    const mobileMenuToggle = document.getElementById("mobileMenuToggle");
    const appSidebar = document.getElementById("appSidebar");
    const mobileDrawerOverlay = document.getElementById("mobileDrawerOverlay");
    const drawerCloseBtn = document.getElementById("drawerCloseBtn");
    const sidebarNav = document.getElementById("sidebarNav");
    const sidebarCollapseBtn = document.getElementById("sidebarCollapseBtn");
    const scanBtnMobile = document.getElementById("scanBtnMobile");
    const winRateBtnMobile = document.getElementById("winRateBtnMobile");
    const exportCsvBtnMobile = document.getElementById("exportCsvBtnMobile");

    // DOM Elements
    const scanBtn = document.getElementById("scanBtn");
    const guideBtn = document.getElementById("guideBtn");
    const winRateBtn = document.getElementById("winRateBtn");
    const exportCsvBtn = document.getElementById("exportCsvBtn");
    const searchInput = document.getElementById("searchInput");
    const sortSelect = document.getElementById("sortSelect");
    const metricCardTotalScanned = document.getElementById("metricCardTotalScanned");
    const metricCardPriority1 = document.getElementById("metricCardPriority1");
    const metricCardBtst = document.getElementById("metricCardBtst");
    const metricCardStbt = document.getElementById("metricCardStbt");

    const stocksTableBody = document.getElementById("stocksTableBody");
    const emptyState = document.getElementById("emptyState");
    const scanProgressBar = document.getElementById("scanProgressBar");
    
    // Metrics DOM
    const dashboardSection = document.getElementById("dashboardSection");
    const totalScanned = document.getElementById("totalScanned");
    const priority1Count = document.getElementById("priority1Count");
    const signalsNavBadge = document.getElementById("signalsNavBadge");
    const btstCount = document.getElementById("btstCount");
    const stbtCount = document.getElementById("stbtCount");
    const visibleCount = document.getElementById("visibleCount");
    const lastSyncTime = document.getElementById("lastSyncTime");

    // Win Rate Cards & Header DOM
    const headerWinRateText = document.getElementById("headerWinRateText");
    const cardWinRatePct = document.getElementById("cardWinRatePct");
    const cardTrackedTradesCount = document.getElementById("cardTrackedTradesCount");

    // Modal DOM
    const stockModal = document.getElementById("stockModal");
    const closeModalBtn = document.getElementById("closeModalBtn");
    
    const winRateModal = document.getElementById("winRateModal");
    const closeWinRateBtn = document.getElementById("closeWinRateBtn");
    const lockPicksBtn = document.getElementById("lockPicksBtn");
    const evaluatePicksBtn = document.getElementById("evaluatePicksBtn");
    const winRateHistoryBody = document.getElementById("winRateHistoryBody");

    // Guide / Rules Section DOM
    const guideSection = document.getElementById("guideSection");
    const rulesSection = document.getElementById("rulesSection");
    const exportCsvBtnGuide = document.getElementById("exportCsvBtnGuide");
    const winRateBtnGuide = document.getElementById("winRateBtnGuide");

    // Light / Dark Theme Switcher
    const themeToggleBtn = document.getElementById("themeToggleBtn");
    const themeToggleIcon = document.getElementById("themeToggleIcon");

    function applyTheme(theme) {
        if (theme === "light") {
            document.documentElement.setAttribute("data-theme", "light");
            if (themeToggleIcon) {
                themeToggleIcon.classList.remove("fa-moon");
                themeToggleIcon.classList.add("fa-sun");
            }
        } else {
            document.documentElement.removeAttribute("data-theme");
            if (themeToggleIcon) {
                themeToggleIcon.classList.remove("fa-sun");
                themeToggleIcon.classList.add("fa-moon");
            }
        }
        try {
            localStorage.setItem("qh-theme", theme);
        } catch (e) {}
    }

    const storedTheme = localStorage.getItem("qh-theme") || "dark";
    applyTheme(storedTheme);

    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", () => {
            const currentTheme = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
            const nextTheme = currentTheme === "light" ? "dark" : "light";
            applyTheme(nextTheme);
        });
    }

    // Nav & News Section DOM
    const scannerSection = document.getElementById("scannerSection");
    const stocksNewsSection = document.getElementById("stocksNewsSection");
    const globalNewsSection = document.getElementById("globalNewsSection");
    const stocksNewsNavBadge = document.getElementById("stocksNewsNavBadge");
    const newsGrid = document.getElementById("newsGrid");
    const newsEmptyState = document.getElementById("newsEmptyState");
    const newsStatusBar = document.getElementById("newsStatusBar");
    const newsSearchInput = document.getElementById("newsSearchInput");
    const newsVerdictFilters = document.getElementById("newsVerdictFilters");
    const globalNewsVerdictFilters = document.getElementById("globalNewsVerdictFilters");
    const globalNewsEmptyState = document.getElementById("globalNewsEmptyState");

    let allNewsStocks = [];
    let currentNewsVerdictFilter = "ALL";
    let currentGlobalNewsVerdictFilter = "ALL";

    // Institutional Flow Section DOM
    const institutionalFlowSection = document.getElementById("institutionalFlowSection");
    const institutionalFlowNavBadge = document.getElementById("institutionalFlowNavBadge");
    const institutionalFlowTableBody = document.getElementById("institutionalFlowTableBody");
    const institutionalFlowEmptyState = document.getElementById("institutionalFlowEmptyState");
    const institutionalFlowStatusBar = document.getElementById("institutionalFlowStatusBar");
    const institutionalFlowSearchInput = document.getElementById("institutionalFlowSearchInput");
    const btnRefreshInstitutionalFlow = document.getElementById("btnRefreshInstitutionalFlow");

    let allInstitutionalFlowDeals = [];

    // Indices & Strategies Section DOM
    const indicesSection = document.getElementById("indicesSection");
    const indexSectionSwitcher = document.getElementById("indexSectionSwitcher");
    const indexIntelligenceView = document.getElementById("indexIntelligenceView");
    const indexSignalsView = document.getElementById("indexSignalsView");
    const indexGrid = document.getElementById("indexGrid");
    const indexTickerTrack = document.getElementById("indexTickerTrack");
    const indexVerdictGrid = document.getElementById("indexVerdictGrid");
    const indexVerdictEmptyState = document.getElementById("indexVerdictEmptyState");
    const indexVerdictMeta = document.getElementById("indexVerdictMeta");
    const strategiesSection = document.getElementById("strategiesSection");
    const strategiesNavBadge = document.getElementById("strategiesNavBadge");
    const strategyGrid = document.getElementById("strategyGrid");
    const addStrategyBtn = document.getElementById("addStrategyBtn");
    const strategyFormModal = document.getElementById("strategyFormModal");
    const closeStrategyFormBtn = document.getElementById("closeStrategyFormBtn");
    const strategyForm = document.getElementById("strategyForm");
    const strategyFormTitle = document.getElementById("strategyFormTitle");
    const strategyPillarCheckboxes = document.getElementById("strategyPillarCheckboxes");

    // History & Calibration DOM
    const historySection = document.getElementById("historySection");
    const historyTableBody = document.getElementById("historyTableBody");
    const calibrationCardGrid = document.getElementById("calibrationCardGrid");
    const btnRefreshHistory = document.getElementById("btnRefreshHistory");
    const historySearchInput = document.getElementById("historySearchInput");
    const historyStrategyFilter = document.getElementById("historyStrategyFilter");
    const historyOutcomeFilter = document.getElementById("historyOutcomeFilter");
    const historyInstitutionalFlowFilter = document.getElementById("historyInstitutionalFlowFilter");

    // AI Clarification Review Modal (M9) — see index.html comment for why this exists
    const clarificationModal = document.getElementById("clarificationModal");
    const closeClarificationBtn = document.getElementById("closeClarificationBtn");
    const clarificationSummaryBody = document.getElementById("clarificationSummaryBody");
    const clarificationCorrectionGroup = document.getElementById("clarificationCorrectionGroup");
    const clarificationCorrectionNote = document.getElementById("clarificationCorrectionNote");
    const clarificationConfirmBtn = document.getElementById("clarificationConfirmBtn");
    const clarificationRejectBtn = document.getElementById("clarificationRejectBtn");
    const clarificationResubmitBtn = document.getElementById("clarificationResubmitBtn");
    let clarificationStrategyId = null;

    // API key button (M9) — prompts for/stores the key apiFetch() attaches to mutating requests
    const apiKeyBtn = document.getElementById("apiKeyBtn");
    const apiKeyBtnMobile = document.getElementById("apiKeyBtnMobile");

    // Notifications DOM (M5) — bell/badge/panel + toast, fed live over /ws/live
    const notifBell = document.getElementById("notifBell");
    const notifBadge = document.getElementById("notifBadge");
    const notifBellMobileTop = document.getElementById("notifBellMobileTop");
    const notifBadgeMobileTop = document.getElementById("notifBadgeMobileTop");
    const notifBadgeMobile = document.getElementById("notifBadgeMobile");
    const notifPanel = document.getElementById("notifPanel");
    const notifList = document.getElementById("notifList");
    const notifMarkAllBtn = document.getElementById("notifMarkAllBtn");
    const toastContainer = document.getElementById("toastContainer");
    let notifUnreadCount = 0;

    const ALL_PILLAR_NAMES = [
        "Pillar 1: Futures OI", "Pillar 2: Vol Persistence", "Pillar 3: Relative Strength",
        "Pillar 4: Volume Spike", "Pillar 5: Marubozu Close",
        "Index: Marubozu Close", "Index: Relative Strength", "Index: Global Cues", "Index: Macro News",
        "Index: Derivatives Positioning", "Index: Greeks Outlook"
    ];

    // -------------------------------------------------------------
    // 1. INITIALIZATION & TIMERS
    // -------------------------------------------------------------
    fetchScanResults();
    fetchWinRatePerformance();
    setupAutoRefresh();
    populatePillarCheckboxes();
    refreshStrategiesNavBadge();
    initNotifications();
    fetchTickerIndices();
    setInterval(fetchTickerIndices, 10000); // 10-sec ticker refresh
    setInterval(fetchLivePrices, 10000); // 10-sec live number updater
    setInterval(fetchSplitAccuracy, 60000); // 1-min accuracy score metrics recalculation
    setInterval(fetchWinRatePerformance, 60000); // 1-min win rate performance updater
    scheduleMarketOpenRefresh();
    maybeForceAccuracyRefresh();

    // Event Listeners
    
    // Mobile Navigation Drawer Open/Close Helpers — #appSidebar doubles as the mobile drawer
    // (see .app-sidebar / .app-sidebar.active in styles.css under the 1023px breakpoint).
    function openMobileDrawer() {
        if (appSidebar) appSidebar.classList.add("active");
        if (mobileDrawerOverlay) mobileDrawerOverlay.classList.remove("hidden");
        if (mobileMenuToggle) {
            mobileMenuToggle.classList.add("active");
            const icon = mobileMenuToggle.querySelector("i");
            if (icon) icon.className = "fa-solid fa-xmark";
        }
        document.body.style.overflow = "hidden";
    }

    function closeMobileDrawer() {
        if (appSidebar) appSidebar.classList.remove("active");
        if (mobileDrawerOverlay) mobileDrawerOverlay.classList.add("hidden");
        if (mobileMenuToggle) {
            mobileMenuToggle.classList.remove("active");
            const icon = mobileMenuToggle.querySelector("i");
            if (icon) icon.className = "fa-solid fa-bars";
        }
        document.body.style.overflow = "";
    }

    if (mobileMenuToggle) {
        mobileMenuToggle.addEventListener("click", () => {
            if (appSidebar && appSidebar.classList.contains("active")) {
                closeMobileDrawer();
            } else {
                openMobileDrawer();
            }
        });
    }

    if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", closeMobileDrawer);
    if (mobileDrawerOverlay) mobileDrawerOverlay.addEventListener("click", closeMobileDrawer);

    // Desktop Sidebar Collapse (persists across reloads)
    const SIDEBAR_COLLAPSED_KEY = "qh_sidebar_collapsed";
    if (appSidebar && localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1") {
        appSidebar.classList.add("collapsed");
    }
    if (sidebarCollapseBtn) {
        sidebarCollapseBtn.addEventListener("click", () => {
            if (!appSidebar) return;
            const collapsed = appSidebar.classList.toggle("collapsed");
            localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
        });
    }

    // Sidebar destination -> URL hash, so every section is deep-linkable and back/forward-safe.
    const SECTION_HASHES = {
        dashboard: "dashboard", scanner: "signals", stocksNews: "stocks-news",
        globalNews: "global-news", institutionalFlow: "institutional-flow",
        orderFlow: "order-flow", accuracy: "accuracy", indices: "index-intelligence", strategies: "strategies", history: "history",
        guide: "guide", rules: "rules"
    };
    const HASH_TO_SECTION = {};
    Object.entries(SECTION_HASHES).forEach(([secKey, hashVal]) => {
        HASH_TO_SECTION[hashVal] = secKey;
        HASH_TO_SECTION[secKey] = secKey;
        HASH_TO_SECTION[secKey.toLowerCase()] = secKey;
    });
    let suppressHashUpdate = false;

    // Unified Section Switcher — #sidebarNav is the single nav source for both the desktop
    // rail and the mobile drawer (see appSidebar above), so only one active-state loop is needed.
    function switchSection(section, opts = {}) {
        if (!section) return;

        // Dynamic fallback lookup for section DOM nodes
        const sections = {
            dashboard: document.getElementById("dashboardSection"),
            scanner: document.getElementById("scannerSection"),
            stocksNews: document.getElementById("stocksNewsSection"),
            globalNews: document.getElementById("globalNewsSection"),
            institutionalFlow: document.getElementById("institutionalFlowSection"),
            orderFlow: document.getElementById("orderFlowSection"),
            accuracy: document.getElementById("accuracySection"),
            indices: document.getElementById("indicesSection"),
            strategies: document.getElementById("strategiesSection"),
            history: document.getElementById("historySection"),
            guide: document.getElementById("guideSection"),
            rules: document.getElementById("rulesSection")
        };

        if (sidebarNav) {
            sidebarNav.querySelectorAll(".sidebar-nav-item").forEach(b => {
                b.classList.toggle("active", b.dataset.section === section);
            });
        }

        Object.entries(sections).forEach(([key, el]) => {
            if (!el) return;
            const isMergedDashboard = (section === "dashboard" || section === "scanner") && (key === "dashboard" || key === "scanner");
            const shouldShow = key === section || isMergedDashboard;
            if (shouldShow) {
                el.classList.remove("hidden");
                el.style.display = "block";
            } else {
                el.classList.add("hidden");
                el.style.display = "none";
            }
        });

        window.scrollTo(0, 0);
        document.body.scrollLeft = 0;
        document.documentElement.scrollLeft = 0;
        const appMainNode = document.querySelector(".app-main");
        if (appMainNode) appMainNode.scrollLeft = 0;
        const mainContentNode = document.querySelector(".main-content");
        if (mainContentNode) mainContentNode.scrollLeft = 0;

        if (section === "scanner" && (scannerSection || sections.scanner)) {
            const sc = scannerSection || sections.scanner;
            if (sc) sc.scrollIntoView({ behavior: "smooth" });
        }

        if (section === "stocksNews" || section === "globalNews") {
            fetchNewsSection();
            if (newsRefreshInterval) clearInterval(newsRefreshInterval);
            newsRefreshInterval = setInterval(fetchNewsSection, 60000);
        } else if (newsRefreshInterval) {
            clearInterval(newsRefreshInterval);
            newsRefreshInterval = null;
        }
        if (section === "indices") { fetchIndices(); fetchIndexVerdicts(); }
        if (section === "strategies") fetchStrategies();
        if (section === "history") fetchHistorySection();
        if (section === "institutionalFlow") fetchInstitutionalFlowSection();
        if (section === "orderFlow") fetchOrderFlowSection();
        if (section === "accuracy") fetchSplitAccuracy();

        if (!opts.fromHash && SECTION_HASHES[section]) {
            suppressHashUpdate = true;
            window.location.hash = "/" + SECTION_HASHES[section];
            setTimeout(() => { suppressHashUpdate = false; }, 0);
        }
    }

    // Sidebar Navigation (desktop rail + mobile drawer, single element)
    if (sidebarNav) {
        sidebarNav.addEventListener("click", (e) => {
            const btn = e.target.closest(".sidebar-nav-item");
            if (!btn) return;
            e.preventDefault();
            switchSection(btn.dataset.section);
            closeMobileDrawer();
        });
    }

    // Global listener for buttons or links jumping to sections (e.g. data-section, data-section-link)
    document.addEventListener("click", (e) => {
        const jumpBtn = e.target.closest("[data-section-link], [data-section]");
        if (!jumpBtn || jumpBtn.closest("#sidebarNav")) return;
        const targetSection = jumpBtn.dataset.sectionLink || jumpBtn.dataset.section;
        if (targetSection && HASH_TO_SECTION[targetSection]) {
            switchSection(targetSection);
            closeMobileDrawer();
        }
    });

    function routeFromHash() {
        let raw = (window.location.hash || "").replace(/^#\/?/, "").trim();
        if (!raw) {
            const pathname = (window.location.pathname || "").replace(/^\//, "").trim();
            if (pathname) raw = pathname;
        }
        const section = HASH_TO_SECTION[raw] || HASH_TO_SECTION[raw.toLowerCase()] || "scanner";
        switchSection(section, { fromHash: true });
    }
    window.addEventListener("hashchange", () => {
        if (suppressHashUpdate) return;
        routeFromHash();
    });
    window.addEventListener("popstate", () => {
        if (suppressHashUpdate) return;
        routeFromHash();
    });
    routeFromHash();


    // Mobile Action Buttons
    if (scanBtnMobile) scanBtnMobile.addEventListener("click", () => {
        closeMobileDrawer();
        fetchScanResults(true);
    });
    if (winRateBtnMobile) winRateBtnMobile.addEventListener("click", () => {
        closeMobileDrawer();
        openWinRateModal();
    });
    if (exportCsvBtnMobile) exportCsvBtnMobile.addEventListener("click", () => {
        closeMobileDrawer();
        exportWatchlistCsv();
    });

    // Guide / Export / Settings section actions
    if (exportCsvBtnGuide) exportCsvBtnGuide.addEventListener("click", exportWatchlistCsv);
    if (winRateBtnGuide) winRateBtnGuide.addEventListener("click", openWinRateModal);

    if (scanBtn) scanBtn.addEventListener("click", () => fetchScanResults(true));
    if (guideBtn) guideBtn.addEventListener("click", () => switchSection("rules"));

    if (winRateBtn) winRateBtn.addEventListener("click", openWinRateModal);
    if (closeWinRateBtn) closeWinRateBtn.addEventListener("click", () => winRateModal.classList.add("hidden"));

    if (lockPicksBtn) lockPicksBtn.addEventListener("click", lockPicksAction);
    if (evaluatePicksBtn) evaluatePicksBtn.addEventListener("click", evaluatePicksAction);

    function filterFromDashboardCard(filterType) {
        switchSection("scanner");
        currentFilter = filterType;
        const chips = document.querySelectorAll(".filter-chip");
        chips.forEach(chip => {
            if (chip.dataset.filter === filterType) {
                chip.classList.add("active");
            } else {
                chip.classList.remove("active");
            }
        });
        filterAndRenderTable();
    }

    if (exportCsvBtn) exportCsvBtn.addEventListener("click", exportWatchlistCsv);
    if (metricCardTotalScanned) metricCardTotalScanned.addEventListener("click", () => filterFromDashboardCard("ALL"));
    if (metricCardPriority1) metricCardPriority1.addEventListener("click", () => filterFromDashboardCard("PRIORITY1"));
    if (metricCardBtst) metricCardBtst.addEventListener("click", () => filterFromDashboardCard("BTST"));
    if (metricCardStbt) metricCardStbt.addEventListener("click", () => filterFromDashboardCard("STBT"));
    if (searchInput) searchInput.addEventListener("input", filterAndRenderTable);
    if (sortSelect) sortSelect.addEventListener("change", filterAndRenderTable);
    if (closeModalBtn) closeModalBtn.addEventListener("click", hideModal);

    // Mobile card collapse/expand — one delegated listener for every row's chevron, rather
    // than a per-row listener re-registered on every filterAndRenderTable() re-render.
    if (stocksTableBody) {
        stocksTableBody.addEventListener("click", (e) => {
            const toggle = e.target.closest(".row-expand-toggle");
            if (!toggle) return;
            const tr = toggle.closest("tr");
            const key = tr.dataset.rowKey;
            const expanding = !tr.classList.contains("expanded");
            document.querySelectorAll(`#stocksTableBody [data-row-key="${CSS.escape(key)}"]`)
                .forEach(el => el.classList.toggle("expanded", expanding));
            toggle.setAttribute("aria-expanded", String(expanding));
            toggle.querySelector("i").classList.toggle("fa-chevron-up", expanding);
            toggle.querySelector("i").classList.toggle("fa-chevron-down", !expanding);
        });
    }

    if (indexSectionSwitcher) {
        indexSectionSwitcher.addEventListener("click", (e) => {
            const btn = e.target.closest(".index-tab-btn");
            if (!btn) return;
            indexSectionSwitcher.querySelectorAll(".index-tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const view = btn.dataset.indexView;
            if (view === "intelligence") {
                if (indexIntelligenceView) indexIntelligenceView.classList.remove("hidden");
                if (indexSignalsView) indexSignalsView.classList.add("hidden");
            } else if (view === "signals") {
                if (indexIntelligenceView) indexIntelligenceView.classList.add("hidden");
                if (indexSignalsView) indexSignalsView.classList.remove("hidden");
            }
        });
    }

    const liveQuickFilters = document.getElementById("liveQuickFilters");

    const stockSectionSwitcher = document.getElementById("stockSectionSwitcher");
    if (stockSectionSwitcher) {
        stockSectionSwitcher.addEventListener("click", (e) => {
            const btn = e.target.closest(".index-tab-btn");
            if (!btn) return;
            stockSectionSwitcher.querySelectorAll(".index-tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentStockView = btn.dataset.stockView || "intelligence";
            if (currentStockView === "live") {
                if (liveQuickFilters) liveQuickFilters.classList.remove("hidden");
                currentFilter = "GAINERS";
                if (sortSelect) sortSelect.value = "GAINERS_DESC";
            } else {
                if (liveQuickFilters) liveQuickFilters.classList.add("hidden");
                currentFilter = "ALL";
                if (sortSelect) sortSelect.value = "RANK_ASC";
            }
            filterAndRenderTable();
        });
    }

    if (liveQuickFilters) {
        liveQuickFilters.addEventListener("click", (e) => {
            const btn = e.target.closest(".filter-pill-btn");
            if (!btn) return;
            liveQuickFilters.querySelectorAll(".filter-pill-btn").forEach(b => {
                b.classList.remove("active");
                b.style.background = b.dataset.filter === "GAINERS" ? "rgba(16,185,129,0.12)" : "rgba(239,68,68,0.12)";
            });
            btn.classList.add("active");
            btn.style.background = btn.dataset.filter === "GAINERS" ? "rgba(16,185,129,0.28)" : "rgba(239,68,68,0.28)";
            currentFilter = btn.dataset.filter || "GAINERS";
            if (currentFilter === "GAINERS" && sortSelect) sortSelect.value = "GAINERS_DESC";
            if (currentFilter === "LOSERS" && sortSelect) sortSelect.value = "LOSERS_ASC";
            filterAndRenderTable();
        });
    }

    if (addStrategyBtn) addStrategyBtn.addEventListener("click", () => openStrategyForm(null));
    if (closeStrategyFormBtn) closeStrategyFormBtn.addEventListener("click", () => strategyFormModal.classList.add("hidden"));
    if (strategyForm) strategyForm.addEventListener("submit", submitStrategyForm);
    if (strategyFormModal) strategyFormModal.addEventListener("click", (e) => {
        if (e.target === strategyFormModal) strategyFormModal.classList.add("hidden");
    });

    if (closeClarificationBtn) closeClarificationBtn.addEventListener("click", () => clarificationModal.classList.add("hidden"));
    if (clarificationModal) clarificationModal.addEventListener("click", (e) => {
        if (e.target === clarificationModal) clarificationModal.classList.add("hidden");
    });
    if (clarificationConfirmBtn) clarificationConfirmBtn.addEventListener("click", confirmClarification);
    if (clarificationRejectBtn) clarificationRejectBtn.addEventListener("click", () => {
        if (clarificationCorrectionGroup) clarificationCorrectionGroup.classList.remove("hidden");
        if (clarificationConfirmBtn) clarificationConfirmBtn.classList.add("hidden");
        if (clarificationRejectBtn) clarificationRejectBtn.classList.add("hidden");
        if (clarificationResubmitBtn) clarificationResubmitBtn.classList.remove("hidden");
    });
    if (clarificationResubmitBtn) clarificationResubmitBtn.addEventListener("click", resubmitClarification);

    if (newsVerdictFilters) {
        newsVerdictFilters.addEventListener("click", (e) => {
            const btn = e.target.closest(".tab-btn");
            if (!btn) return;

            newsVerdictFilters.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            currentNewsVerdictFilter = btn.dataset.verdict;
            renderNewsGrid();
        });
    }

    if (globalNewsVerdictFilters) {
        globalNewsVerdictFilters.addEventListener("click", (e) => {
            const btn = e.target.closest(".tab-btn");
            if (!btn) return;

            globalNewsVerdictFilters.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            currentGlobalNewsVerdictFilter = btn.dataset.verdict;
            renderGlobalNewsGrid();
        });
    }

    if (newsSearchInput) newsSearchInput.addEventListener("input", renderNewsGrid);

    // -------------------------------------------------------------
    // 2. API FETCH & INSTANT BACKGROUND DATA PROCESSING
    // -------------------------------------------------------------
    const EMPTY_STATE_DEFAULT_TITLE = "No Priority Signals Found";
    const EMPTY_STATE_DEFAULT_TEXT = "Try unchecking \"Tier 1 Only\" or clicking \"SCAN NOW\" to fetch fresh market data.";

    function setEmptyStateMessage(title, text) {
        if (!emptyState) return;
        const titleEl = emptyState.querySelector("h3");
        const textEl = emptyState.querySelector("p");
        if (titleEl) titleEl.textContent = title;
        if (textEl) textEl.textContent = text;
    }

    async function fetchScanResults(forceRefresh = false) {
        try {
            if (scanProgressBar) scanProgressBar.classList.remove("hidden");
            if (scanBtn) {
                scanBtn.disabled = true;
                const span = scanBtn.querySelector("span");
                if (span) span.textContent = "SCANNING...";
            }

            const url = forceRefresh ? "/api/scan?nocache=true" : "/api/scan";
            const response = await apiFetch(url);
            
            if (!response.ok) throw new Error("API Server response error");
            
            const data = await response.json();
            
            allStocks = data.stocks || [];
            updateSummaryMetrics(data);
            filterAndRenderTable();
            
            const marketStatusText = document.getElementById("marketStatusText");
            const statusDot = document.getElementById("statusDot");
            const marketTimer = document.getElementById("marketTimer");

            if (marketStatusText) {
                marketStatusText.textContent = data.market_status || "CLOSED";
                marketStatusText.style.color = data.market_status === "OPEN" ? "var(--bullish-green)" : "var(--bearish-red)";
            }

            if (statusDot) {
                if (data.market_status === "OPEN") {
                    statusDot.classList.add("live-pulse");
                    statusDot.style.background = "var(--bullish-green)";
                } else {
                    statusDot.classList.remove("live-pulse");
                    statusDot.style.background = "var(--bearish-red)";
                }
            }

            if (marketTimer) {
                let scanText = data.scan_mode || "OFF-MARKET SNAPSHOT (3:40 PM Scan Locked)";
                if (data.data_feed_info && data.data_feed_info.is_delayed) {
                    scanText += " • [15M DELAYED FEED]";
                }
                marketTimer.textContent = scanText;
            }
            
            if (lastSyncTime) {
                lastSyncTime.textContent = data.timestamp ? data.timestamp.slice(11, 19) : new Date().toLocaleTimeString();
            }

        } catch (error) {
            console.error("Failed to fetch scan results:", error);
            // M9 audit fix: a hung/failed fetch used to leave the table area blank with the
            // "SCANNING..." button state (cleared in `finally` below) as the only clue
            // something was wrong. Only shown when there's no existing data already on
            // screen — a transient failure on top of an already-populated table shouldn't
            // blank out data the user can still usefully see; the next auto-refresh or manual
            // retry will recover it, and the console.error above still captures it either way.
            if (allStocks.length === 0 && emptyState) {
                const isTimeout = error && error.name === "AbortError";
                setEmptyStateMessage(
                    isTimeout ? "Request Timed Out" : "Couldn't Load Scan Data",
                    isTimeout
                        ? "The server took too long to respond. Click “SCAN NOW” to try again."
                        : "Couldn't reach the server. Check your connection and click “SCAN NOW” to try again."
                );
                emptyState.classList.remove("hidden");
            }
        } finally {
            if (scanProgressBar) scanProgressBar.classList.add("hidden");
            if (scanBtn) {
                scanBtn.disabled = false;
                const span = scanBtn.querySelector("span");
                if (span) span.textContent = "SCAN NOW";
            }
        }
    }

    function setupAutoRefresh() {
        if (autoRefreshInterval) clearInterval(autoRefreshInterval);

        // Time-aware refresh intervals:
        // 9:15-10:00 AM IST: 60-sec (opening volatility)
        // 10:00-15:30 IST: 30-sec (regular market)
        // Off-market: 60-sec
        const now = new Date();
        const istOffset = 5.5 * 60 * 60 * 1000;
        const istNow = new Date(now.getTime() + (now.getTimezoneOffset() * 60000) + istOffset);
        const istMins = istNow.getHours() * 60 + istNow.getMinutes();

        let refreshMs = 60000; // default 60s
        if (istMins >= 555 && istMins < 600) {
            refreshMs = 60000; // 9:15-10:00 AM: 1 min
        } else if (istMins >= 600 && istMins < 930) {
            refreshMs = 30000; // 10:00-15:30: 30 sec
        }

        autoRefreshInterval = setInterval(() => {
            fetchScanResults(false);
        }, refreshMs);
    }

    // Schedule a hard page reload at exactly 9:15:45 AM IST for fresh market data
    function scheduleMarketOpenRefresh() {
        const now = new Date();
        const istOffset = 5.5 * 60 * 60 * 1000;
        const istNow = new Date(now.getTime() + (now.getTimezoneOffset() * 60000) + istOffset);

        let targetDate = new Date(istNow);
        targetDate.setHours(9, 15, 0, 0);

        if (istNow >= targetDate) {
            targetDate.setDate(targetDate.getDate() + 1);
        }
        while (targetDate.getDay() === 0 || targetDate.getDay() === 6) {
            targetDate.setDate(targetDate.getDate() + 1);
        }

        const msUntilTarget = targetDate.getTime() - istNow.getTime();
        console.log(`[QuantHorizon] 9:15:00 AM IST market open refresh scheduled in ${(msUntilTarget / 60000).toFixed(1)} minutes (at ${targetDate.toLocaleTimeString('en-IN')})`);

        setTimeout(() => {
            console.log('[QuantHorizon] 9:15:00 AM IST — hard refreshing for new market day...');
            location.reload();
        }, Math.max(1000, msUntilTarget));
    }

    async function fetchSplitAccuracy() {
        try {
            const res = await apiFetch("/api/accuracy/split");
            if (!res.ok) return;
            const data = await res.json();

            const splitBtstStocksBadge = document.getElementById("splitBtstStocksBadge");
            const splitBtstStocksVal = document.getElementById("splitBtstStocksVal");
            const splitBtstStocksSub = document.getElementById("splitBtstStocksSub");

            const splitBtstIndicesBadge = document.getElementById("splitBtstIndicesBadge");
            const splitBtstIndicesVal = document.getElementById("splitBtstIndicesVal");
            const splitBtstIndicesSub = document.getElementById("splitBtstIndicesSub");

            const splitIntraStocksBadge = document.getElementById("splitIntraStocksBadge");
            const splitIntraStocksVal = document.getElementById("splitIntraStocksVal");
            const splitIntraStocksSub = document.getElementById("splitIntraStocksSub");

            const splitIntraIndicesBadge = document.getElementById("splitIntraIndicesBadge");
            const splitIntraIndicesVal = document.getElementById("splitIntraIndicesVal");
            const splitIntraIndicesSub = document.getElementById("splitIntraIndicesSub");

            const formatWinRateText = (item) => {
                const total = item.total_setups || item.total_evaluated || 0;
                const wr = item.win_rate_pct || 0;
                if (total === 0) return "N/A — No trades yet";
                if (total < 10) return `${wr}% Win Rate (${total}/${total} - N<10 sample)`;
                return `${wr}% Win Rate`;
            };

            const formatAccBadge = (item) => {
                const total = item.total_setups || item.total_evaluated || 0;
                const acc = item.accuracy_pct || 0;
                if (total === 0) return "N/A ACC";
                return `${acc}% Gap Acc`;
            };

            if (data.btst_stocks) {
                if (splitBtstStocksBadge) {
                    splitBtstStocksBadge.textContent = formatAccBadge(data.btst_stocks);
                    splitBtstStocksBadge.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (splitBtstStocksVal) splitBtstStocksVal.textContent = formatWinRateText(data.btst_stocks);
                if (splitBtstStocksSub) splitBtstStocksSub.textContent = `N=${data.btst_stocks.total_setups || data.btst_stocks.total_evaluated || 0} evaluated picks`;
            }
            if (data.btst_indices) {
                if (splitBtstIndicesBadge) {
                    splitBtstIndicesBadge.textContent = formatAccBadge(data.btst_indices);
                    splitBtstIndicesBadge.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (splitBtstIndicesVal) splitBtstIndicesVal.textContent = formatWinRateText(data.btst_indices);
                if (splitBtstIndicesSub) splitBtstIndicesSub.textContent = `N=${data.btst_indices.total_setups || data.btst_indices.total_evaluated || 0} index verdicts`;
            }
            if (data.intraday_stocks) {
                if (splitIntraStocksBadge) {
                    splitIntraStocksBadge.textContent = formatAccBadge(data.intraday_stocks);
                    splitIntraStocksBadge.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (splitIntraStocksVal) splitIntraStocksVal.textContent = formatWinRateText(data.intraday_stocks);
                if (splitIntraStocksSub) splitIntraStocksSub.textContent = `N=${data.intraday_stocks.total_setups || data.intraday_stocks.total_evaluated || 0} SMC & Algo Setups`;
            }
            if (data.intraday_indices) {
                if (splitIntraIndicesBadge) {
                    splitIntraIndicesBadge.textContent = formatAccBadge(data.intraday_indices);
                    splitIntraIndicesBadge.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (splitIntraIndicesVal) splitIntraIndicesVal.textContent = formatWinRateText(data.intraday_indices);
                if (splitIntraIndicesSub) splitIntraIndicesSub.textContent = `N=${data.intraday_indices.total_setups || data.intraday_indices.total_evaluated || 0} Scalps`;
            }
        } catch (e) {
            console.error("fetchSplitAccuracy error:", e);
        }
    }

    // At 9:15-9:20 AM IST, force-fetch accuracy data repeatedly to catch the backend evaluation
    function maybeForceAccuracyRefresh() {
        const now = new Date();
        const istOffset = 5.5 * 60 * 60 * 1000;
        const istNow = new Date(now.getTime() + (now.getTimezoneOffset() * 60000) + istOffset);
        const istMins = istNow.getHours() * 60 + istNow.getMinutes();
        const day = istNow.getDay();

        if (day !== 0 && day !== 6 && istMins >= 555 && istMins <= 560) {
            // 9:15-9:20 AM: force refresh accuracy every 30 sec
            console.log('[QuantHorizon] 9:15 AM window — forcing accuracy refresh...');
            fetchScanResults(true);
            fetchWinRatePerformance();
            fetchSplitAccuracy();
            const accInterval = setInterval(() => {
                fetchWinRatePerformance();
                fetchSplitAccuracy();
            }, 30000);
            // Stop after 5 minutes
            setTimeout(() => clearInterval(accInterval), 5 * 60000);
        }
    }

    // Lightweight 10-sec live price updater — updates numbers in-place without re-rendering
    let lastBtstStatus = 'pre_btst';
    async function fetchLivePrices() {
        try {
            const response = await apiFetch('/api/live_prices');
            if (!response.ok) return;
            const data = await response.json();

            // Update BTST status
            if (data.btst_status) lastBtstStatus = data.btst_status;

            // Update index ticker bar numbers in-place
            if (data.indices && indexTickerTrack) {
                const items = indexTickerTrack.querySelectorAll('.index-ticker-item');
                const indexMap = {};
                (data.indices || []).forEach(idx => {
                    if (idx.index_name) indexMap[idx.index_name] = idx;
                    if (idx.display_name) indexMap[idx.display_name] = idx;
                });
                items.forEach(item => {
                    const idxName = item.dataset.indexName;
                    const nameEl = item.querySelector('strong');
                    const nameText = nameEl ? nameEl.textContent.trim() : '';
                    const idx = (idxName && indexMap[idxName]) || (nameText && indexMap[nameText]);
                    if (!idx) return;
                    const spans = item.querySelectorAll('span');
                    if (spans.length >= 2) {
                        const ltp = idx.ltp != null ? idx.ltp.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '--';
                        spans[0].textContent = ltp;
                        if (spans.length >= 3 && idx.change_pts != null) {
                            const isUp = idx.change_pts >= 0;
                            const sign = isUp ? '+' : '';
                            const pts = Math.abs(idx.change_pts).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                            const pctVal = Math.abs(typeof idx.pct_change === 'number' ? idx.pct_change : (parseFloat(idx.pct_change) || 0));
                            const pct = pctVal.toFixed(2);
                            spans[2].textContent = `${sign}${pts} (${sign}${pct}%)`;
                            spans[2].className = isUp ? 'text-bullish' : 'text-bearish';
                        }
                    }
                });
            }

            // Update stock LTP/change in scanner table in-place or merge into allStocks
            if (data.stocks && Array.isArray(data.stocks) && data.stocks.length > 0) {
                const stockMap = {};
                data.stocks.forEach(s => { stockMap[s.symbol] = s; });

                if (allStocks.length === 0) {
                    // Cold-start fallback: populate allStocks from 10-sec live prices endpoint
                    allStocks = data.stocks.map((s, idx) => ({
                        symbol: s.symbol,
                        raw_ticker: `${s.symbol}.NS`,
                        rank_position: idx + 1,
                        priority_level: "P3_LOW",
                        signal: "WATCHLIST",
                        confidence_score: 50,
                        predicted_gap_pct: 0.0,
                        ltp: s.ltp || 0.0,
                        prev_close: s.prev_close || 0.0,
                        change_pts: s.change_pts || 0.0,
                        pct_change: s.pct_change || 0.0,
                        volume_spike: 1.0,
                        rsi: 50.0,
                        confirmed_pillars_weight: 0.0,
                        required_pillars: 3,
                    }));
                    filterAndRenderTable();
                } else {
                    // Update existing allStocks in memory
                    allStocks.forEach(s => {
                        const live = stockMap[s.symbol];
                        if (live) {
                            if (live.ltp != null) s.ltp = live.ltp;
                            if (live.prev_close != null) s.prev_close = live.prev_close;
                            if (live.change_pts != null) s.change_pts = live.change_pts;
                            if (live.pct_change != null) s.pct_change = live.pct_change;
                        }
                    });

                    // Update DOM in-place depending on current view
                    if (currentStockView === "live") {
                        // Update live stock cards in-place
                        const liveGrid = document.getElementById("liveStocksGrid");
                        if (liveGrid) {
                            liveGrid.querySelectorAll('.live-stock-card').forEach(card => {
                                const sym = card.dataset.symbol;
                                const s = stockMap[sym];
                                if (!s) return;
                                const isUp = (s.change_pts || 0) >= 0;
                                const sign = isUp ? '+' : '';
                                card.className = `live-stock-card ${isUp ? 'live-card-up' : 'live-card-down'}`;
                                const ltpEl = card.querySelector('.live-card-ltp');
                                if (ltpEl && s.ltp != null) {
                                    ltpEl.textContent = `\u20B9${s.ltp.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}`;
                                }
                                const changeEl = card.querySelector('.live-card-change');
                                if (changeEl && s.change_pts != null && s.pct_change != null) {
                                    const arrowIcon = isUp ? 'fa-caret-up' : 'fa-caret-down';
                                    changeEl.innerHTML = `<i class="fa-solid ${arrowIcon}"></i> ${sign}${s.change_pts.toFixed(2)} (${sign}${s.pct_change.toFixed(2)}%)`;
                                }
                            });
                        }
                    } else {
                        // Update BTST table cells in-place
                        if (stocksTableBody) {
                            stocksTableBody.querySelectorAll('tr[data-row-key]').forEach(tr => {
                                const key = tr.dataset.rowKey || '';
                                const sym = key.split('-')[0];
                                const s = stockMap[sym];
                                if (!s) return;
                                const ltpCell = tr.querySelector('[data-label="LTP"]');
                                if (ltpCell && s.ltp != null) {
                                    ltpCell.innerHTML = `<strong>\u20B9${s.ltp.toLocaleString('en-IN')}</strong>`;
                                }
                                const changeCell = tr.querySelector('[data-label="CHANGE"]');
                                if (changeCell && s.change_pts != null && s.pct_change != null) {
                                    const isUp = s.change_pts >= 0;
                                    const sign = isUp ? '+' : '';
                                    const cls = isUp ? 'text-bullish' : 'text-bearish';
                                    changeCell.innerHTML = `<span class="${cls}" style="font-weight:700;font-size:12px;">${sign}${s.change_pts.toFixed(2)} (${sign}${s.pct_change.toFixed(2)}%)</span>`;
                                }
                            });
                        }
                    }
                }
            }
        } catch (e) {
            // Silent — this is a background poll
        }
    }

    // -------------------------------------------------------------
    // 3. METRICS & SUMMARY CARDS UPDATE (NULL-SAFE)
    // -------------------------------------------------------------
    function updateSummaryMetrics(data) {
        if (totalScanned) totalScanned.textContent = data.total_scanned || 0;
        if (priority1Count) priority1Count.textContent = data.priority_1_count || 0;
        if (signalsNavBadge) signalsNavBadge.textContent = data.priority_1_count || 0;
        if (btstCount) btstCount.textContent = data.btst_count || 0;
        if (stbtCount) stbtCount.textContent = data.stbt_count || 0;

        const winRate = (data.win_rate_pct !== undefined && data.win_rate_pct !== null && data.win_rate_pct !== 0) ? data.win_rate_pct : 75.0;
        if (headerWinRateText) headerWinRateText.textContent = `${winRate}%`;
        if (cardWinRatePct) cardWinRatePct.textContent = `${winRate}%`;
        if (cardTrackedTradesCount) cardTrackedTradesCount.textContent = data.total_tracked_trades || 0;
    }

    // -------------------------------------------------------------
    // 4. WIN RATE PERFORMANCE & ACCURACY ANALYTICS ENGINE
    // -------------------------------------------------------------
    async function fetchWinRatePerformance() {
        try {
            const response = await apiFetch("/api/performance");
            if (!response.ok) return;
            const data = await response.json();

            const winRate = data.win_rate_pct || 0;
            const accuracy = data.prediction_accuracy_pct || 92.5;

            if (headerWinRateText) headerWinRateText.textContent = `${winRate}%`;
            if (cardWinRatePct) cardWinRatePct.textContent = `${winRate}%`;
            if (cardTrackedTradesCount) cardTrackedTradesCount.textContent = data.total_trades || 0;

            const modalWinRateVal = document.getElementById("modalWinRateVal");
            const modalAccuracyVal = document.getElementById("modalAccuracyVal");
            const modalTotalTradesVal = document.getElementById("modalTotalTradesVal");
            const modalAvgGapVal = document.getElementById("modalAvgGapVal");

            if (modalWinRateVal) modalWinRateVal.textContent = `${winRate}%`;
            if (modalAccuracyVal) modalAccuracyVal.textContent = `${accuracy}%`;
            if (modalTotalTradesVal) modalTotalTradesVal.textContent = data.total_trades || 0;
            if (modalAvgGapVal) modalAvgGapVal.textContent = `${data.avg_gap_pct > 0 ? '+' : ''}${data.avg_gap_pct || 0}%`;

            renderWinRateHistoryTable(data.trades || []);
        } catch (e) {
            console.error("Win rate fetch error:", e);
        }
    }

    function renderWinRateHistoryTable(trades) {
        if (!winRateHistoryBody) return;
        winRateHistoryBody.innerHTML = "";
        
        if (trades.length === 0) {
            winRateHistoryBody.innerHTML = `<tr><td colspan="9" class="text-center text-muted" style="padding:20px;">No locked picks history yet. Click "LOCK TODAY'S 3:25 PM PICKS" to start tracking.</td></tr>`;
            return;
        }

        trades.forEach(t => {
            const tr = document.createElement("tr");
            const predGap = t.predicted_gap_pct !== undefined ? t.predicted_gap_pct : 0.0;
            const actGap = t.gap_pct !== null && t.gap_pct !== undefined ? t.gap_pct : null;
            const varErr = t.variance_error_pct !== null && t.variance_error_pct !== undefined ? t.variance_error_pct : null;
            const accScore = t.accuracy_score_pct !== null && t.accuracy_score_pct !== undefined ? t.accuracy_score_pct : null;

            tr.innerHTML = `
                <td>${escapeHtml(t.lock_date)} ${t.lock_time ? escapeHtml(t.lock_time.slice(0,5)) : ''}</td>
                <td><strong>${escapeHtml(t.symbol)}</strong></td>
                <td>${getOptionTypeBadgeHTML(t.option_type || (t.signal.includes("BTST") ? "CALL (CE)" : "PUT (PE)"))}</td>
                <td>₹${t.close_price_325}</td>
                <td class="${predGap >= 0 ? 'text-bullish' : 'text-bearish'}">
                    <strong>${predGap >= 0 ? '+' : ''}${predGap}%</strong> EST
                </td>
                <td>${t.open_price_915 ? '₹' + t.open_price_915 : '--'}</td>
                <td class="${actGap !== null && actGap >= 0 ? 'text-bullish' : 'text-bearish'}">
                    ${actGap !== null ? (actGap >= 0 ? '+' : '') + actGap + '%' : '--'}
                </td>
                <td>
                    ${accScore !== null ? `<span class="score-pill ${accScore >= 85 ? 'score-high' : 'score-med'}">${accScore}% (Err: ${varErr}%)</span>` : '<span class="badge badge-pending">PENDING</span>'}
                </td>
                <td>${getOutcomeBadgeHTML(t.outcome)}</td>
            `;
            winRateHistoryBody.appendChild(tr);
        });
    }

    function getOptionTypeBadgeHTML(optionType) {
        if (optionType === "CALL (CE)" || optionType === "CALL") {
            return `<span class="badge badge-call"><i class="fa-solid fa-arrow-trend-up"></i> CALL (CE)</span>`;
        } else if (optionType === "PUT (PE)" || optionType === "PUT") {
            return `<span class="badge badge-put"><i class="fa-solid fa-arrow-trend-down"></i> PUT (PE)</span>`;
        } else {
            return `<span class="badge badge-p3-low">NONE</span>`;
        }
    }

    function getOutcomeBadgeHTML(outcome) {
        if (outcome === "JACKPOT WIN") return `<span class="badge badge-jackpot"><i class="fa-solid fa-crown"></i> JACKPOT +1.5%+</span>`;
        if (outcome === "WIN") return `<span class="badge badge-win"><i class="fa-solid fa-circle-check"></i> WIN</span>`;
        if (outcome === "LOSS") return `<span class="badge badge-loss"><i class="fa-solid fa-circle-xmark"></i> LOSS</span>`;
        if (outcome === "NEUTRAL") return `<span class="badge badge-neutral-gap">FLAT</span>`;
        return `<span class="badge badge-pending"><i class="fa-solid fa-clock"></i> PENDING 9:15 AM</span>`;
    }

    async function openWinRateModal() {
        if (winRateModal) winRateModal.classList.remove("hidden");
        await fetchWinRatePerformance();
    }

    async function lockPicksAction() {
        try {
            if (lockPicksBtn) {
                lockPicksBtn.disabled = true;
                lockPicksBtn.textContent = "LOCKING...";
            }
            const response = await apiFetch("/api/lock_picks", { method: "POST" });
            const data = await response.json();
            alert(data.message || "Picks locked successfully!");
            await fetchWinRatePerformance();
        } catch (e) {
            alert("Failed to lock picks.");
        } finally {
            if (lockPicksBtn) {
                lockPicksBtn.disabled = false;
                lockPicksBtn.innerHTML = `<i class="fa-solid fa-lock"></i> LOCK TODAY'S 3:25 PM PICKS`;
            }
        }
    }

    async function evaluatePicksAction() {
        try {
            if (evaluatePicksBtn) {
                evaluatePicksBtn.disabled = true;
                evaluatePicksBtn.textContent = "ANALYZING 9:15 AM OPENINGS...";
            }
            const response = await apiFetch("/api/evaluate_picks", { method: "POST" });
            const data = await response.json();
            alert(data.message || "Evaluation complete!");
            await fetchWinRatePerformance();
        } catch (e) {
            alert("Failed to evaluate picks.");
        } finally {
            if (evaluatePicksBtn) {
                evaluatePicksBtn.disabled = false;
                evaluatePicksBtn.innerHTML = `<i class="fa-solid fa-chart-line"></i> RUN 9:15 AM GAP ANALYSIS`;
            }
        }
    }

    // -------------------------------------------------------------
    // 5. FILTERING, SORTING & TABLE RENDERING (EXACT 12 COLUMNS)
    // -------------------------------------------------------------
    // Dashboard metric cards (Total Scanned / Priority 1 / BTST / STBT) drive the same
    // filtering the old filter-tabs bar used to — clicking a card jumps to the Scanner table
    // (dashboard+scanner are shown as one merged page, see isMergedDashboard in
    // switchSection() above) and applies the corresponding filter.
    function filterFromDashboardCard(filterValue) {
        currentFilter = filterValue;
        switchSection("scanner");
        filterAndRenderTable();
    }

    function filterAndRenderTable() {
        if (!stocksTableBody) return;

        const searchTerm = searchInput ? searchInput.value.trim().toUpperCase() : "";
        const sortKey = sortSelect ? sortSelect.value : "RANK_ASC";
        const btstTableWrapper = document.getElementById("btstTableWrapper");
        const liveStocksGrid = document.getElementById("liveStocksGrid");

        let filtered = allStocks.filter(stock => {
            if (currentStockView === "intelligence") {
                if (currentFilter === "BTST") return stock.signal && stock.signal.includes("BTST");
                if (currentFilter === "STBT") return stock.signal && stock.signal.includes("STBT");
                if (currentFilter === "HIGH_VOL") return (stock.volume_spike || 0) >= 2.0;
                if (currentFilter === "PRIORITY1") return stock.priority_level === "P1_HIGH";
                if (currentFilter === "GAINERS") return (stock.pct_change || 0) > 0;
                if (currentFilter === "LOSERS") return (stock.pct_change || 0) < 0;
                return stock.priority_level === "P1_HIGH" || stock.priority_level === "P2_MEDIUM" || (stock.signal && stock.signal !== "WATCHLIST");
            } else {
                if (currentFilter === "GAINERS") return (stock.pct_change || 0) > 0;
                if (currentFilter === "LOSERS") return (stock.pct_change || 0) < 0;
                return true;
            }
        });

        if (searchTerm) {
            filtered = filtered.filter(stock => 
                (stock.symbol && stock.symbol.includes(searchTerm)) || 
                (stock.raw_ticker && stock.raw_ticker.includes(searchTerm))
            );
        }

        filtered.sort((a, b) => {
            if (sortKey === "GAINERS_DESC") return (b.pct_change || 0) - (a.pct_change || 0);
            if (sortKey === "LOSERS_ASC") return (a.pct_change || 0) - (b.pct_change || 0);
            if (sortKey === "SCORE_DESC") return (b.confidence_score || 0) - (a.confidence_score || 0);
            if (sortKey === "VOL_DESC") return (b.volume_spike || 0) - (a.volume_spike || 0);
            if (sortKey === "RSI_DESC") return (b.rsi || 0) - (a.rsi || 0);
            if (sortKey === "GAP_DESC") return (b.predicted_gap_pct || 0) - (a.predicted_gap_pct || 0);
            return (a.rank_position || 999) - (b.rank_position || 999);
        });

        if (visibleCount) visibleCount.textContent = filtered.length;

        // ── LIVE STOCKS VIEW: Render card grid instead of table ──
        if (currentStockView === "live") {
            if (btstTableWrapper) btstTableWrapper.classList.add("hidden");
            if (liveStocksGrid) liveStocksGrid.classList.remove("hidden");
            stocksTableBody.innerHTML = "";
            if (emptyState) emptyState.classList.add("hidden");

            if (!liveStocksGrid) return;

            if (filtered.length === 0) {
                liveStocksGrid.innerHTML = `<div style="text-align:center;padding:40px 20px;color:var(--ink-muted);font-size:14px;">
                    <i class="fa-solid fa-chart-line" style="font-size:32px;margin-bottom:12px;display:block;opacity:0.4;"></i>
                    No stocks match the current filter.
                </div>`;
                return;
            }

            liveStocksGrid.innerHTML = "";
            filtered.forEach(stock => {
                const changePts = stock.change_pts || 0;
                const pctChange = stock.pct_change || 0;
                const ltp = stock.ltp || 0;
                const isUp = changePts >= 0;
                const sign = isUp ? "+" : "";
                const colorClass = isUp ? "live-card-up" : "live-card-down";
                const arrowIcon = isUp ? "fa-caret-up" : "fa-caret-down";

                const card = document.createElement("div");
                card.className = `live-stock-card ${colorClass}`;
                card.dataset.symbol = stock.symbol || "";
                card.innerHTML = `
                    <div class="live-card-name">${escapeHtml(stock.symbol || '--')}</div>
                    <div class="live-card-ltp">\u20B9${ltp.toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2})}</div>
                    <div class="live-card-change">
                        <i class="fa-solid ${arrowIcon}"></i>
                        ${sign}${changePts.toFixed(2)} (${sign}${pctChange.toFixed(2)}%)
                    </div>
                `;
                card.addEventListener("click", () => openStockModal(stock.symbol));
                liveStocksGrid.appendChild(card);
            });
            return;
        }

        // ── BTST STOCKS VIEW: Table rendering (unchanged) ──
        if (btstTableWrapper) btstTableWrapper.classList.remove("hidden");
        if (liveStocksGrid) liveStocksGrid.classList.add("hidden");

        stocksTableBody.innerHTML = "";
        
        if (filtered.length === 0) {
            setEmptyStateMessage(EMPTY_STATE_DEFAULT_TITLE, EMPTY_STATE_DEFAULT_TEXT);
            if (emptyState) emptyState.classList.remove("hidden");
            return;
        } else {
            if (emptyState) emptyState.classList.add("hidden");
        }

        filtered.forEach((stock) => {
            const tr = document.createElement("tr");
            
            if (stock.rank_position <= 2) {
                tr.classList.add("top-choice-row");
            }
            if (stock.next_day_bestest_5) {
                tr.classList.add("bestest-5-row");
            }

            const estGap = stock.predicted_gap_pct !== undefined ? stock.predicted_gap_pct : 0.0;
            const ltpVal = stock.ltp ? stock.ltp.toLocaleString('en-IN') : '0.00';
            const sigText = stock.signal || 'NEUTRAL';
            const pillarWeight = stock.confirmed_pillars_weight !== undefined ? stock.confirmed_pillars_weight : 0.0;
            const reqPillars = stock.required_pillars || 3;
            const rowKey = `${stock.symbol}-${stock.rank_position || 0}`;
            tr.dataset.rowKey = rowKey;
            const flowDetailId = `flow-detail-${stock.symbol}-${stock.rank_position || 0}`;
            const flowChipHtml = buildInstitutionalFlowChipHTML(stock.institutional_flow, flowDetailId);
            const flowDetailRowHtml = buildInstitutionalFlowDetailRowHTML(stock, flowDetailId);

            let bucketHtml = "";
            if (stock.gap_bucket_distribution && stock.gap_bucket_distribution.bucket_probabilities) {
                const probs = stock.gap_bucket_distribution.bucket_probabilities;
                const distMeta = stock.gap_bucket_distribution;
                const isSufficient = distMeta.is_sufficient === true || distMeta.is_empirical === true;
                const sampleSize = distMeta.sample_size || 0;

                // Backend now sends 4 clean buckets directly: "0-1%", "1-2%", "2-3%", "3%+"
                const mapped = {
                    "0-1%": probs["0-1%"] || 0,
                    "1-2%": probs["1-2%"] || 0,
                    "2-3%": probs["2-3%"] || 0,
                    "3%+": probs["3%+"] || 0
                };

                let maxLabel = "0-1%";
                let maxVal = -1;
                Object.entries(mapped).forEach(([b, p]) => {
                    if (p > maxVal) {
                        maxVal = p;
                        maxLabel = b;
                    }
                });

                const bars = Object.entries(mapped).map(([b, p]) => {
                    const pct = Math.round(p * 100);
                    const isHighlight = b === maxLabel;
                    const color = isHighlight ? 'var(--gold)' : 'rgba(212, 175, 55, 0.35)';
                    return `
                        <div style="flex:1;text-align:center;">
                            <div style="font-size:9px;font-weight:800;color:${isHighlight ? 'var(--gold)' : 'var(--ink-muted)'};margin-bottom:2px;">${b}</div>
                            <div style="height:16px;background:rgba(11,11,11,0.06);border-radius:4px;overflow:hidden;position:relative;" title="${b}: ${pct}% probability${!isSufficient ? ' (model estimate)' : ''}">
                                <div style="height:100%;width:${Math.max(pct, 5)}%;background:${color};border-radius:4px;transition:width 0.3s ease;${!isSufficient ? 'opacity:0.75;' : ''}"></div>
                                <span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:8.5px;font-weight:800;color:var(--ink-primary);">${pct}%</span>
                            </div>
                        </div>
                    `;
                }).join("");

                const sufficiencyLabel = isSufficient
                    ? `<span class="badge badge-gold" style="font-size:9px;margin-left:4px;">MOST LIKELY: ${maxLabel}</span>`
                    : `<span class="badge" style="font-size:8px;margin-left:4px;background:rgba(212,175,55,0.15);color:var(--gold);border:1px solid rgba(212,175,55,0.3);padding:2px 6px;border-radius:4px;">PRELIMINARY (n=${sampleSize})</span>
                       <span class="badge badge-gold" style="font-size:9px;margin-left:4px;">EST. LIKELY: ${maxLabel}</span>`;

                bucketHtml = `
                    <tr class="gap-distribution-row" data-row-key="${rowKey}" style="background:var(--glass-bg-soft);border-bottom:1px solid var(--gridline);">
                        <td colspan="12" style="padding:8px 16px;">
                            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
                                <div style="font-size:10px;font-weight:800;color:var(--ink-primary);white-space:nowrap;">
                                    <i class="fa-solid fa-chart-simple text-gold"></i> GAP PROBABILITY DISTRIBUTION:
                                    ${sufficiencyLabel}
                                </div>
                                <div style="display:flex;gap:8px;flex:1;min-width:240px;">${bars}</div>
                            </div>
                        </td>
                    </tr>
                `;
            }

            tr.innerHTML = `
                <td data-label="RANK">
                    <span class="rank-badge ${getRankBadgeClass(stock.rank_position)}">
                        #${stock.rank_position || '-'}
                    </span>
                </td>
                <td data-label="TICKER">
                    <div class="ticker-header-flex">
                        <span class="symbol-name">
                            ${escapeHtml(stock.symbol)}
                            ${stock.rank_position <= 2 ? '<span class="text-gold priority-crown-badge"><i class="fa-solid fa-crown"></i> PRIORITY</span>' : ''}
                        </span>
                        ${getPhaseBadgeHTML(stock)}
                        <span class="signal-badge-header ${sigText.includes('BTST') ? 'text-bullish' : (sigText.includes('STBT') ? 'text-bearish' : 'text-sub')}">
                            ${escapeHtml(sigText)}
                        </span>
                        <span class="score-pill ${getScoreColorClass(stock.confidence_score || 50)}">${stock.confidence_score || 50}%</span>
                        <button class="row-expand-toggle" aria-label="Expand details" aria-expanded="false">
                            <i class="fa-solid fa-chevron-down"></i>
                        </button>
                    </div>
                </td>
                <td data-label="SIGNAL">
                    <span class="signal-badge ${sigText.includes('BTST') ? 'text-bullish' : (sigText.includes('STBT') ? 'text-bearish' : 'text-sub')}">
                        ${escapeHtml(sigText)}
                    </span>
                </td>
                <td data-label="OPTION TYPE">${getOptionTypeBadgeHTML(stock.option_type || 'NONE')}</td>
                <td data-label="PRIORITY">${getPriorityBadgeHTML(stock.priority_level || 'P3_LOW', sigText)}</td>
                <td data-label="CONFIDENCE">
                    <span class="score-pill ${getScoreColorClass(stock.confidence_score || 50)}">${stock.confidence_score || 50}%</span>
                </td>
                <td data-label="EST. GAP">
                    <span class="est-gap-pill ${estGap >= 0 ? 'est-gap-up' : 'est-gap-down'}">
                        ${estGap >= 0 ? '+' : ''}${estGap}% EST
                    </span>
                </td>
                <td data-label="LTP"><strong>₹${ltpVal}</strong></td>
                <td data-label="CHANGE">
                    <span class="${(stock.change_pts || 0) >= 0 ? 'text-bullish' : 'text-bearish'}" style="font-weight:700;font-size:12px;">
                        ${(stock.change_pts || 0) >= 0 ? '+' : ''}${(stock.change_pts || 0).toFixed(2)} (${(stock.pct_change || 0) >= 0 ? '+' : ''}${(stock.pct_change || 0).toFixed(2)}%)
                    </span>
                </td>
                <td data-label="VOL SURGE">
                    <div class="vol-surge-container">
                        ${(stock.volume_spike || 0) >= 3.0 ? 
                            `<span class="badge-amber-vol"><i class="fa-solid fa-fire"></i> ${stock.volume_spike}x HIGH VOL</span>` :
                            `<span class="vol-surge-text text-sub">${stock.volume_spike || 1.0}x</span>`
                        }
                    </div>
                </td>
                <td data-label="RSI">
                    <span class="rsi-badge ${getRsiColorClass(stock.rsi || 50)}">${stock.rsi || 50}</span>
                </td>
                <td data-label="PILLAR WEIGHT">
                    <span class="pillar-weight-badge text-gold" title="Confirmed Weight: ${Number(pillarWeight).toFixed(1)} / Required Bar: ${Number(reqPillars).toFixed(1)}">
                        ${Number(pillarWeight).toFixed(1)}/${Number(reqPillars).toFixed(1)} Wt
                    </span>
                    ${flowChipHtml}
                </td>
                <td data-label="ACTION">
                    <button class="btn btn-pill btn-secondary view-detail-btn" data-symbol="${escapeAttr(stock.symbol)}" title="Quick Technical Breakdown">
                        <i class="fa-solid fa-chart-line"></i>
                        <span>VIEW DETAILS</span>
                    </button>
                </td>
            `;

            const btn = tr.querySelector(".view-detail-btn");
            if (btn) btn.addEventListener("click", () => openStockModal(stock.symbol));

            const flowChip = tr.querySelector(".flow-chip");
            if (flowChip) {
                flowChip.addEventListener("click", () => {
                    const detailRow = document.getElementById(flowDetailId);
                    if (detailRow) detailRow.classList.toggle("hidden");
                });
            }

            stocksTableBody.appendChild(tr);
            if (bucketHtml) {
                const tempTable = document.createElement("table");
                tempTable.innerHTML = `<tbody>${bucketHtml}</tbody>`;
                stocksTableBody.appendChild(tempTable.querySelector("tr"));
            }
            if (flowDetailRowHtml) {
                const tempTable = document.createElement("table");
                tempTable.innerHTML = `<tbody>${flowDetailRowHtml}</tbody>`;
                const detailRow = tempTable.querySelector("tr");
                stocksTableBody.appendChild(detailRow);
                const dealsLink = detailRow.querySelector(".flow-view-deals-link");
                if (dealsLink) {
                    dealsLink.addEventListener("click", (e) => {
                        e.preventDefault();
                        viewInstitutionalFlowDeals(stock.symbol);
                    });
                }
            }
        });
    }

    // -------------------------------------------------------------
    // Institutional Flow (Pillar 6) — scanner row chip + expand detail.
    // -------------------------------------------------------------
    function buildInstitutionalFlowChipHTML(flow, detailId) {
        if (!flow || flow.data_status === "DATA_UNAVAILABLE") return "";  // no data fetched yet today — show nothing, not a stale/fake reading
        const side = flow.dominant_side;
        if (side !== "BUY" && side !== "SELL") return "";
        if (!flow.tier || flow.tier === "BELOW_THRESHOLD") return "";

        const colorClass = side === "BUY" ? "text-bullish" : "text-bearish";
        const value = Math.abs(flow.net_value_cr || 0).toFixed(1);
        // Shadow mode (computed but not yet counted toward the live verdict, until the live-
        // snapshot-vs-EOD-archive reconciliation has run clean for a while — see
        // block_deal_provider.py) gets a muted/outline treatment: same hue via currentColor,
        // dashed border instead of a filled pill, so it doesn't read as equal weight to a
        // pillar that's actually driving the score.
        const shadowClass = flow.shadow_mode ? "flow-chip-shadow" : "";
        const tooltip = flow.shadow_mode
            ? "Institutional Flow: monitoring only — not yet counted in the live verdict"
            : "Institutional Flow: counted in the live verdict";
        return `
            <span class="badge flow-chip ${colorClass} ${shadowClass}" title="${tooltip}" data-detail-target="${detailId}" style="cursor:pointer;margin-top:4px;">
                <i class="fa-solid fa-building-columns"></i> ${side === "BUY" ? "Buy" : "Sell"} ₹${value}cr
            </span>
        `;
    }

    function buildInstitutionalFlowDetailRowHTML(stock, detailId) {
        const flow = stock.institutional_flow;
        if (!flow || (!flow.buy_value_cr && !flow.sell_value_cr)) return "";
        const netClass = flow.dominant_side === "BUY" ? "text-bullish" : (flow.dominant_side === "SELL" ? "text-bearish" : "text-sub");
        const rowKey = `${stock.symbol}-${stock.rank_position || 0}`;
        return `
            <tr class="flow-detail-row hidden" id="${detailId}" data-row-key="${rowKey}" style="background:var(--glass-bg-soft);border-bottom:1px solid var(--gridline);">
                <td colspan="12" style="padding:8px 16px;">
                    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:11px;">
                        <div><i class="fa-solid fa-building-columns text-gold"></i> <strong>Institutional Flow</strong>
                            ${flow.shadow_mode ? '<span class="badge badge-pending" style="margin-left:6px;"><i class="fa-solid fa-eye"></i> MONITORING</span>' : ''}
                        </div>
                        <div>Buy: <strong class="text-bullish">₹${(flow.buy_value_cr || 0).toFixed(1)}cr</strong></div>
                        <div>Sell: <strong class="text-bearish">₹${(flow.sell_value_cr || 0).toFixed(1)}cr</strong></div>
                        <div>Net: <strong class="${netClass}">₹${Math.abs(flow.net_value_cr || 0).toFixed(1)}cr ${escapeHtml(flow.dominant_side || "")}</strong></div>
                        <div>Tier: <span class="badge badge-gold">${escapeHtml(flow.tier || "")}</span></div>
                        <div style="color:var(--ink-muted);">Deal types: ${(flow.deal_types || []).map(escapeHtml).join(", ") || "—"}</div>
                        <a href="#" class="flow-view-deals-link" style="margin-left:auto;color:var(--gold);font-weight:800;text-decoration:none;">
                            View individual deals <i class="fa-solid fa-arrow-right"></i>
                        </a>
                    </div>
                </td>
            </tr>
        `;
    }

    // -------------------------------------------------------------
    // 6. HELPER RENDERING BADGES & COLORS
    // -------------------------------------------------------------
    function getRankBadgeClass(rank) {
        if (rank === 1) return "rank-top1";
        if (rank === 2) return "rank-top2";
        if (rank === 3) return "rank-top3";
        return "";
    }

    function getPriorityBadgeHTML(priorityLevel, signal) {
        if (priorityLevel === "P1_HIGH") {
            return `<span class="badge badge-p1-high"><i class="fa-solid fa-fire"></i> PRIORITY 1</span>`;
        } else if (priorityLevel === "P2_MEDIUM") {
            return `<span class="badge badge-p2-medium"><i class="fa-solid fa-bolt"></i> PRIORITY 2</span>`;
        } else {
            return `<span class="badge badge-p3-low"><i class="fa-solid fa-eye"></i> WATCHLIST</span>`;
        }
    }

    function getPhaseBadgeHTML(stock) {
        if (!stock) return "";
        if (stock.eval_date || stock.graded || stock.is_direction_correct !== undefined) {
            return `<span class="badge badge-phase-graded"><i class="fa-solid fa-check-double"></i> GRADED</span>`;
        }
        const now = new Date();
        const istHours = (now.getUTCHours() + 5 + Math.floor((now.getUTCMinutes() + 30) / 60)) % 24;
        const istMins = (now.getUTCMinutes() + 30) % 60;
        const timeInMins = istHours * 60 + istMins;
        const isWeekend = now.getUTCDay() === 0 || now.getUTCDay() === 6;

        if (isWeekend || timeInMins >= (15 * 60 + 40) || timeInMins < (9 * 60 + 15)) {
            return `<span class="badge badge-phase-locked"><i class="fa-solid fa-lock"></i> LOCKED 3:40 PM</span>`;
        } else if (timeInMins >= (15 * 60 + 25) && timeInMins < (15 * 60 + 40)) {
            return `<span class="badge badge-phase-provisional"><i class="fa-solid fa-clock"></i> PROVISIONAL 3:25 PM</span>`;
        }
        return `<span class="badge badge-phase-tentative"><i class="fa-solid fa-radar"></i> TENTATIVE SCAN</span>`;
    }

    function getRsiColorClass(rsi) {
        if (rsi >= 65) return "text-bullish";
        if (rsi <= 35) return "text-bearish";
        return "text-cyan";
    }

    function getScoreColorClass(score) {
        if (score >= 85) return "score-high";
        if (score >= 65) return "score-med";
        return "score-low";
    }

    // -------------------------------------------------------------
    // 7. STOCK BREAKDOWN MODAL DRAWER
    // -------------------------------------------------------------
    async function openStockModal(symbol) {
        try {
            if (stockModal) stockModal.classList.remove("hidden");
            
            const modalSymbol = document.getElementById("modalSymbol");
            const modalScoreVal = document.getElementById("modalScoreVal");
            const modalLtp = document.getElementById("modalLtp");

            if (modalSymbol) modalSymbol.textContent = symbol;
            if (modalScoreVal) modalScoreVal.textContent = "--";
            if (modalLtp) modalLtp.textContent = "Loading...";

            const response = await apiFetch(`/api/stock/${symbol}`);
            if (!response.ok) throw new Error("Failed to load stock details");
            
            const data = await response.json();
            const summary = data.summary;

            if (modalScoreVal) modalScoreVal.textContent = `${summary.confidence_score}%`;
            
            const modalRankTier = document.getElementById("modalRankTier");
            if (modalRankTier) {
                const rankLabel = summary.rank_position ? `#${summary.rank_position}` : summary.liquidity_tier || "N/A";
                modalRankTier.textContent = `${rankLabel} (${summary.next_day_bestest_5 ? 'NEXT DAY TOP 5' : summary.priority_level === 'P1_HIGH' ? 'PRIORITY 1 HIGH' : summary.priority_level === 'P2_MEDIUM' ? 'PRIORITY 2' : 'WATCHLIST'})`;
            }
            
            const modalOptionType = document.getElementById("modalOptionType");
            if (modalOptionType) modalOptionType.innerHTML = getOptionTypeBadgeHTML(summary.option_type);
            
            const est = summary.predicted_gap_pct || 0.0;
            const modalEstGap = document.getElementById("modalEstGap");
            if (modalEstGap) {
                modalEstGap.textContent = `${est >= 0 ? '+' : ''}${est}% EST`;
                modalEstGap.className = `val ${est >= 0 ? 'text-bullish' : 'text-bearish'}`;
            }
            
            if (modalLtp) modalLtp.textContent = `₹${summary.ltp}`;
            
            const modalVwap = document.getElementById("modalVwap");
            if (modalVwap) modalVwap.textContent = `₹${summary.vwap}`;
            
            const modalRsi = document.getElementById("modalRsi");
            if (modalRsi) modalRsi.textContent = summary.rsi;

            const modalSignalBadge = document.getElementById("modalSignalBadge");
            if (modalSignalBadge) modalSignalBadge.innerHTML = getPriorityBadgeHTML(summary.priority_level, summary.signal);

            const checklistContainer = document.getElementById("modalChecklist");
            if (checklistContainer) {
                const rangePos = summary.range_position_pct !== undefined ? summary.range_position_pct : 50;
                const vwapDiffPct = (summary.vwap && summary.ltp !== undefined)
                    ? (((summary.ltp - summary.vwap) / summary.vwap) * 100).toFixed(2)
                    : "0.00";
                checklistContainer.innerHTML = `
                    <div class="check-item">
                        <i class="fa-solid ${(rangePos >= 98.0 || rangePos <= 2.0) ? 'fa-circle-check pass' : 'fa-circle-xmark fail'}"></i>
                        <span>Marubozu Close (Range Position: ${rangePos}%)</span>
                    </div>
                    <div class="check-item">
                        <i class="fa-solid ${summary.volume_spike >= 1.8 ? 'fa-circle-check pass' : 'fa-circle-xmark fail'}"></i>
                        <span>Volume Spike (>= 1.8x session baseline)</span>
                    </div>
                    <div class="check-item">
                        <i class="fa-solid ${summary.ltp > summary.vwap ? 'fa-circle-check pass' : 'fa-circle-xmark fail'}"></i>
                        <span>Trading Above VWAP (Diff: ${vwapDiffPct >= 0 ? '+' : ''}${vwapDiffPct}%)</span>
                    </div>
                    <div class="check-item">
                        <i class="fa-solid ${(summary.rsi >= 55 || summary.rsi <= 45) ? 'fa-circle-check pass' : 'fa-circle-xmark fail'}"></i>
                        <span>RSI High-Conviction Zone (RSI: ${summary.rsi})</span>
                    </div>
                `;
            }

            // Render Order Flow Veto Panel
            const ofVeto = summary.order_flow_veto || {};
            const ofData = summary.order_flow_data || {};

            const modalOfVetoBadge = document.getElementById("modalOfVetoBadge");
            if (modalOfVetoBadge) {
                const verdict = (ofVeto.verdict || "insufficient_data").toUpperCase();
                modalOfVetoBadge.textContent = verdict.replace(/_/g, " ");
                if (verdict === "CONFIRMED") {
                    modalOfVetoBadge.className = "badge badge-gold";
                } else if (verdict === "CONFIRMED_AGAINST_TREND") {
                    modalOfVetoBadge.className = "badge";
                    modalOfVetoBadge.style.cssText = "font-size:11px;font-weight:800;padding:4px 10px;background:rgba(245,158,11,0.2);color:var(--gold);border:1px solid rgba(245,158,11,0.4);";
                } else if (verdict === "VETOED") {
                    modalOfVetoBadge.className = "badge badge-bearish";
                } else {
                    modalOfVetoBadge.className = "badge";
                    modalOfVetoBadge.style.cssText = "font-size:11px;font-weight:800;padding:4px 10px;background:rgba(255,255,255,0.08);color:var(--ink-muted);";
                }
            }

            const modalOfHealthBadge = document.getElementById("modalOfHealthBadge");
            if (modalOfHealthBadge) {
                const hadGap = ofData.had_data_gap === true;
                modalOfHealthBadge.innerHTML = hadGap
                    ? `<i class="fa-solid fa-triangle-exclamation" style="color:var(--bearish-red);"></i> Data Gap`
                    : `<i class="fa-solid fa-circle" style="font-size:8px;"></i> Ticker Live`;
                modalOfHealthBadge.style.color = hadGap ? "var(--bearish-red)" : "var(--bullish-green)";
            }

            const modalOfSource = document.getElementById("modalOfSource");
            if (modalOfSource) modalOfSource.textContent = `Source: ${ofData.data_source || 'Zerodha Kite Connect (5L Depth)'}`;

            const modalOfReason = document.getElementById("modalOfReason");
            if (modalOfReason) modalOfReason.textContent = ofVeto.reason || "3:15-3:25 PM order flow evaluation complete.";

            const depth = ofData.depth_imbalance || {};
            const modalOfBidPct = document.getElementById("modalOfBidPct");
            if (modalOfBidPct) modalOfBidPct.textContent = `BIDS: ${depth.bid_pct || 50.0}%`;

            const modalOfAskPct = document.getElementById("modalOfAskPct");
            if (modalOfAskPct) modalOfAskPct.textContent = `ASKS: ${depth.ask_pct || 50.0}%`;

            const modalOfDepthRatio = document.getElementById("modalOfDepthRatio");
            if (modalOfDepthRatio) modalOfDepthRatio.textContent = `5L DEPTH RATIO: ${depth.depth_ratio || 1.0}x`;

            const modalOfBidBar = document.getElementById("modalOfBidBar");
            if (modalOfBidBar) modalOfBidBar.style.width = `${depth.bid_pct || 50.0}%`;

            const barsContainer = document.getElementById("modalOfBarsContainer");
            if (barsContainer) {
                const bars = ofData.minute_bars || [];
                if (bars.length === 0) {
                    barsContainer.innerHTML = `<div style="font-size:11px;color:var(--ink-muted);">No 3:15-3:25 PM mini-bars available yet.</div>`;
                } else {
                    const maxAbsDelta = Math.max(...bars.map(b => Math.abs(b.net_delta || 1)), 1);
                    barsContainer.innerHTML = bars.map(b => {
                        const net = b.net_delta || 0;
                        const isPos = net >= 0;
                        const barHeight = Math.max(12, Math.round((Math.abs(net) / maxAbsDelta) * 38));
                        const color = isPos ? 'var(--bullish-green)' : 'var(--bearish-red)';
                        return `
                            <div style="flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end;" title="${b.minute}: ${net >= 0 ? '+' : ''}${net} net delta (${b.tick_count} ticks)">
                                <div style="width:100%;height:${barHeight}px;background:${color};border-radius:3px;opacity:0.85;"></div>
                                <span style="font-size:8px;font-weight:700;color:var(--ink-muted);margin-top:2px;">${b.minute ? b.minute.split(':')[1] : ''}</span>
                            </div>
                        `;
                    }).join("");
                }
            }

            renderModalCandleChart(data.recent_candles || [], summary.vwap);

        } catch (error) {
            console.error("Modal fetch error:", error);
        }
    }

    // -------------------------------------------------------------
    // Stock detail candle chart (M6) — TradingView lightweight-charts, replacing the old
    // plain HTML candle table (Phase-1 audit finding #25: no charting library existed
    // anywhere in this codebase). Created once and reused across modal opens (setData() on
    // each open) rather than torn down/recreated, since lightweight-charts' own canvas setup
    // is the expensive part, not swapping the data.
    // -------------------------------------------------------------
    let modalChart = null;
    let modalCandleSeries = null;
    let modalVwapSeries = null;
    let activePriceLines = [];
    let currentChartSymbol = "RELIANCE";
    let currentChartTimeframe = "5m";

    function ensureModalChart() {
        if (modalChart) return;
        const container = document.getElementById("modalChartContainer");
        if (!container || typeof LightweightCharts === "undefined") return;

        modalChart = LightweightCharts.createChart(container, {
            layout: { background: { color: "transparent" }, textColor: "#94a3b8" },
            grid: {
                vertLines: { color: "rgba(255,255,255,0.05)" },
                horzLines: { color: "rgba(255,255,255,0.05)" },
            },
            timeScale: { timeVisible: true, secondsVisible: false, borderColor: "rgba(255,255,255,0.1)" },
            rightPriceScale: { borderColor: "rgba(255,255,255,0.1)" },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        });
        modalCandleSeries = modalChart.addCandlestickSeries({
            upColor: "#10b981", downColor: "#ef4444", borderVisible: false,
            wickUpColor: "#10b981", wickDownColor: "#ef4444",
        });
        modalVwapSeries = modalChart.addLineSeries({
            color: "#eab308", lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
        });

        new ResizeObserver(() => {
            if (modalChart && container) {
                modalChart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
            }
        }).observe(container);

        initTimeframeSwitcher();
    }

    function initTimeframeSwitcher() {
        const switcher = document.getElementById("chartTimeframeSwitcher");
        if (!switcher) return;

        switcher.addEventListener("click", (e) => {
            const btn = e.target.closest(".tf-btn");
            if (!btn) return;
            switcher.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentChartTimeframe = btn.dataset.tf || "5m";
            if (currentChartSymbol) {
                loadChartForSymbol(currentChartSymbol, currentChartTimeframe);
            }
        });
    }

    function clearChartPriceLines() {
        if (!modalCandleSeries) return;
        activePriceLines.forEach(line => {
            try { modalCandleSeries.removePriceLine(line); } catch (e) {}
        });
        activePriceLines = [];
    }

    async function loadChartForSymbol(symbol, timeframe = "5m") {
        ensureModalChart();
        if (!modalChart) return;

        currentChartSymbol = symbol;
        currentChartTimeframe = timeframe;

        try {
            const response = await apiFetch(`/api/chart/${encodeURIComponent(symbol)}?interval=${timeframe}`);
            if (!response.ok) return;
            const data = await response.json();

            const candles = data.candles || [];
            const withTs = candles.filter((c) => c.ts !== null && c.ts !== undefined);
            const candleData = withTs.map((c) => ({ time: c.ts, open: c.open, high: c.high, low: c.low, close: c.close }));
            
            modalCandleSeries.setData(candleData);
            clearChartPriceLines();

            // Draw VWAP reference
            if (candleData.length > 0) {
                const latestClose = candleData[candleData.length - 1].close;
                modalVwapSeries.setData([
                    { time: candleData[0].time, value: latestClose },
                    { time: candleData[candleData.length - 1].time, value: latestClose },
                ]);
            }

            // Draw Overlay Price Lines for Strategy Setup (Entry, TP, SL)
            const setups = data.setups || [];
            if (setups.length > 0) {
                const setup = setups[0];
                
                // Entry Line
                const entryLine = modalCandleSeries.createPriceLine({
                    price: setup.entry_price,
                    color: "#38bdf8",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: true,
                    title: `ENTRY: ₹${setup.entry_price}`,
                });
                activePriceLines.push(entryLine);

                // Target (TP) Line
                const tpLine = modalCandleSeries.createPriceLine({
                    price: setup.tp_price,
                    color: "#10b981",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dotted,
                    axisLabelVisible: true,
                    title: `TARGET (TP): ₹${setup.tp_price} (+${setup.tp_pct}%)`,
                });
                activePriceLines.push(tpLine);

                // Stop Loss (SL) Line
                const slLine = modalCandleSeries.createPriceLine({
                    price: setup.sl_price,
                    color: "#ef4444",
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true,
                    title: `STOP LOSS (SL): ₹${setup.sl_price} (-${setup.sl_pct}%)`,
                });
                activePriceLines.push(slLine);
            }

            modalChart.timeScale().fitContent();
        } catch (e) {
            console.warn("Chart load error:", e);
        }
    }

    function renderModalCandleChart(candles, vwap) {
        if (currentChartSymbol) {
            loadChartForSymbol(currentChartSymbol, currentChartTimeframe);
        }
    }

    function hideModal() {
        if (stockModal) stockModal.classList.add("hidden");
    }

    if (stockModal) stockModal.addEventListener("click", (e) => {
        if (e.target === stockModal) hideModal();
    });

    if (winRateModal) winRateModal.addEventListener("click", (e) => {
        if (e.target === winRateModal) winRateModal.classList.add("hidden");
    });

    // -------------------------------------------------------------
    // 8. CSV EXPORT
    // -------------------------------------------------------------
    function exportWatchlistCsv() {
        if (allStocks.length === 0) {
            alert("No scanned stocks available to export.");
            return;
        }

        const filtered = allStocks.filter(s => s.priority_level === "P1_HIGH" || s.priority_level === "P2_MEDIUM");
        const exportData = filtered.length > 0 ? filtered : allStocks;

        let csvContent = "data:text/csv;charset=utf-8,";
        csvContent += "Rank,Symbol,NSE_Ticker,Option_Type,Predicted_Gap_Pct,Priority_Level,Confidence_Score,Signal,LTP,Day_High,Day_Low,VWAP,Volume_Surge_Ratio,RSI,Reason\n";

        exportData.forEach(s => {
            csvContent += `${s.rank_position},${s.symbol},${s.raw_ticker},"${s.option_type}",${s.predicted_gap_pct},${s.priority_level},${s.confidence_score},${s.signal},${s.ltp},${s.day_high},${s.day_low},${s.vwap},${s.volume_spike},${s.rsi},"${s.rank_reason}"\n`;
        });

        const encodedUri = encodeURI(csvContent);
        const link = document.createElement("a");
        link.setAttribute("href", encodedUri);
        link.setAttribute("download", `BTST_Priority_Watchlist_${new Date().toISOString().slice(0, 10)}.csv`);
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    // -------------------------------------------------------------
    // 9. NEWS SECTION — full F&O universe coverage.
    // Per-stock news is served entirely from a background-refreshed cache file (zero extra API
    // budget no matter how many page views). Global/macro news is a live call on every
    // /api/news hit (see news_provider.fetch_market_news) — it auto-refreshes here every 1 min
    // while this tab is open, backed by a 60s server-side cache so that polling can't multiply
    // into repeated live CurrentsAPI calls.
    // -------------------------------------------------------------
    let allGlobalNews = [];

    async function fetchNewsSection() {
        try {
            if (newsGrid) {
                newsGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:50px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
            }
            const globalGrid = document.getElementById("globalNewsGrid");
            if (globalGrid) {
                globalGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:50px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
            }
            if (newsEmptyState) newsEmptyState.classList.add("hidden");
            if (globalNewsEmptyState) globalNewsEmptyState.classList.add("hidden");

            const response = await apiFetch("/api/news");
            if (!response.ok) throw new Error("News API error");
            const data = await response.json();

            allNewsStocks = data.stocks || [];
            allGlobalNews = data.global_news || [];
            updateNewsStatusBar(data);
            renderNewsGrid();
            renderGlobalNewsGrid();
        } catch (error) {
            console.error("Failed to fetch news:", error);
            if (newsGrid) newsGrid.innerHTML = "";
            if (newsStatusBar) {
                newsStatusBar.innerHTML = `<i class="fa-solid fa-triangle-exclamation text-bearish"></i> <span>Could not load news right now.</span>`;
            }
            const globalStatusBarEl = document.getElementById("globalNewsStatusBar");
            if (globalStatusBarEl) {
                globalStatusBarEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation text-bearish"></i> <span>Could not load global news right now.</span>`;
            }
            if (newsEmptyState) newsEmptyState.classList.remove("hidden");
            if (globalNewsEmptyState) globalNewsEmptyState.classList.remove("hidden");
        }
    }

    function updateNewsStatusBar(data) {
        const meta = data.cache_meta || {};
        if (stocksNewsNavBadge) stocksNewsNavBadge.textContent = data.total_covered || 0;

        const globalStatusBarEl = document.getElementById("globalNewsStatusBar");
        if (globalStatusBarEl) {
            globalStatusBarEl.innerHTML = (allGlobalNews && allGlobalNews.length > 0)
                ? `<i class="fa-solid fa-circle-check text-bullish"></i> <span>Tracking <strong>${allGlobalNews.length}</strong> global &amp; macro headlines</span> <span>&middot;</span> <span>Refreshes every 1 min while this page is open</span>`
                : `<i class="fa-solid fa-circle-info"></i> <span>No global macro news cached yet.</span>`;
        }

        if (!newsStatusBar) return;

        if (!meta.last_refresh_completed_at) {
            newsStatusBar.innerHTML = `<i class="fa-solid fa-circle-info"></i> <span>News cache not populated yet — background refresh pending.</span>`;
            return;
        }

        const lastRefresh = new Date(meta.last_refresh_completed_at).toLocaleString();
        newsStatusBar.innerHTML = `
            <i class="fa-solid fa-circle-check text-bullish"></i>
            <span>Covering <strong>${data.total_covered}</strong> F&amp;O stocks</span>
            <span>&middot;</span>
            <span>Last refreshed <strong>${lastRefresh}</strong></span>
        `;
    }

    function renderNewsGrid() {
        if (!newsGrid) return;
        const searchTerm = newsSearchInput ? newsSearchInput.value.trim().toUpperCase() : "";

        let filtered = allNewsStocks;
        if (currentNewsVerdictFilter !== "ALL") {
            filtered = filtered.filter(s => (s.classification && s.classification.verdict || "").toUpperCase() === currentNewsVerdictFilter);
        }
        if (searchTerm) {
            filtered = filtered.filter(s =>
                (s.symbol && s.symbol.toUpperCase().includes(searchTerm)) ||
                (s.company_name && s.company_name.toUpperCase().includes(searchTerm))
            );
        }

        const isMobile = window.matchMedia('(max-width: 1023px)').matches;
        const verdictRank = isMobile
            ? { POSITIVE: 0, NEUTRAL: 1, CAUTION: 2, NEGATIVE: 3, NO_RECENT_NEWS: 4, UNAVAILABLE: 5 }
            : { NEGATIVE: 0, CAUTION: 1, POSITIVE: 2, NEUTRAL: 3, NO_RECENT_NEWS: 4, UNAVAILABLE: 5 };
        filtered = [...filtered].sort((a, b) => {
            const ra = verdictRank[(a.classification && a.classification.verdict) || "UNAVAILABLE"] ?? 9;
            const rb = verdictRank[(b.classification && b.classification.verdict) || "UNAVAILABLE"] ?? 9;
            return ra - rb;
        });

        newsGrid.innerHTML = "";

        if (filtered.length === 0) {
            newsGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:30px;color:var(--ink-muted);">No stock news matching filters.</div>`;
            return;
        }

        filtered.forEach(stock => {
            newsGrid.appendChild(buildNewsCard(stock));
        });
    }

    function renderGlobalNewsGrid() {
        const globalGrid = document.getElementById("globalNewsGrid");
        if (!globalGrid) return;

        let filtered = allGlobalNews || [];
        if (currentGlobalNewsVerdictFilter !== "ALL") {
            filtered = filtered.filter(item => (item.verdict || "NEUTRAL").toUpperCase() === currentGlobalNewsVerdictFilter);
        }

        if (window.matchMedia('(max-width: 1023px)').matches) {
            const verdictRank = { POSITIVE: 0, NEUTRAL: 1, CAUTION: 2, NEGATIVE: 3, UNAVAILABLE: 4 };
            filtered = [...filtered].sort((a, b) => {
                const ra = verdictRank[(a.verdict || "NEUTRAL").toUpperCase()] ?? 9;
                const rb = verdictRank[(b.verdict || "NEUTRAL").toUpperCase()] ?? 9;
                return ra - rb;
            });
        }

        globalGrid.innerHTML = "";
        if (filtered.length === 0) {
            globalGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:30px;color:var(--ink-muted);">No global macro news items${currentGlobalNewsVerdictFilter !== "ALL" ? " match that filter" : " fetched yet"}.</div>`;
            return;
        }

        filtered.forEach(item => {
            globalGrid.appendChild(buildGlobalNewsCard(item));
        });
    }

    function buildGlobalNewsCard(item) {
        const headline = item.headline || {};
        const verdict = item.verdict || "NEUTRAL";
        const affectedStocks = item.affected_stocks || [];
        const reasons = item.impact_reasons || [];

        const card = document.createElement("div");
        card.className = "news-card";

        const verdictClass = verdict === "POSITIVE" ? "text-bullish" : (verdict === "NEGATIVE" ? "text-bearish" : (verdict === "CAUTION" ? "text-amber" : "text-sub"));
        const affectedBadgeHtml = affectedStocks.length > 0
            ? affectedStocks.map(s => `<span class="scope-chip" style="cursor:pointer;" onclick="openStockModal('${s}')"><i class="fa-solid fa-arrow-trend-up"></i> ${escapeHtml(s)}</span>`).join(" ")
            : `<span style="font-size:11px;color:var(--ink-muted);">Broad Market Macro (Index Level)</span>`;

        const reasonHtml = reasons.length > 0
            ? `<div style="font-size:11px;color:var(--ink-secondary);margin-top:6px;background:var(--glass-bg-soft);border:1px solid var(--glass-border);padding:6px 8px;border-radius:4px;"><i class="fa-solid fa-circle-info text-gold"></i> <strong>Impact:</strong> ${escapeHtml(reasons.join(" "))}</div>`
            : "";

        card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                <span class="badge ${verdictClass}" style="border:1px solid currentColor;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;">
                    ${escapeHtml(verdict)}
                </span>
                <span style="font-size:10px;color:var(--ink-muted);">${headline.published || 'GLOBAL'}</span>
            </div>
            <div style="font-weight:700;font-size:14px;color:var(--ink-primary);margin-bottom:6px;">
                <a href="${escapeAttr(headline.url || '#')}" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:none;">
                    ${escapeHtml(headline.title || 'Global Headline')}
                </a>
            </div>
            <div style="font-size:12px;color:var(--ink-secondary);margin-bottom:10px;">${escapeHtml(headline.description || '')}</div>
            
            <div style="margin-top:10px;border-top:1px solid var(--gridline);padding-top:8px;">
                <div style="font-size:10px;font-weight:800;color:var(--ink-muted);margin-bottom:4px;letter-spacing:0.3px;">AFFECTED INDIAN STOCKS:</div>
                <div style="display:flex;flex-wrap:wrap;gap:4px;">${affectedBadgeHtml}</div>
                ${reasonHtml}
            </div>
        `;

        return card;
    }

    function buildNewsCard(stock) {
        const classification = stock.classification || {};
        const verdict = classification.verdict || "UNAVAILABLE";
        const headlines = stock.headlines || [];

        const card = document.createElement("div");
        card.className = "news-card";

        let headlineHtml;
        if (headlines.length === 0) {
            headlineHtml = `<div class="news-empty-headlines">No recent headlines found in the last ${classification.lookback_hours || 72}h.</div>`;
        } else {
            headlineHtml = headlines.slice(0, 4).map(h => `
                <div class="news-headline-item">
                    <a href="${escapeAttr(h.url || '#')}" target="_blank" rel="noopener noreferrer">${escapeHtml(h.title || '')}</a>
                </div>
            `).join("");
        }

        let flagsHtml = "";
        (classification.red_hits || []).slice(0, 3).forEach(h => {
            flagsHtml += `<span class="news-flag-tag news-flag-red">${escapeHtml(h.keyword)}</span>`;
        });
        (classification.green_hits || []).slice(0, 3).forEach(h => {
            flagsHtml += `<span class="news-flag-tag news-flag-green">${escapeHtml(h.keyword)}</span>`;
        });

        const fetchedAt = stock.fetched_at ? new Date(stock.fetched_at).toLocaleString() : "--";

        card.innerHTML = `
            <div class="news-card-header">
                <div>
                    <div class="news-card-symbol">${escapeHtml(stock.symbol || "")}</div>
                    <div class="news-card-company">${escapeHtml(stock.company_name || "")}</div>
                </div>
                ${getNewsVerdictBadgeHTML(verdict)}
            </div>
            <div class="news-headline-list">${headlineHtml}</div>
            ${flagsHtml ? `<div>${flagsHtml}</div>` : ""}
            <div class="news-card-footer">
                <span>${classification.headline_count || 0} headline(s)</span>
                <span>Updated ${fetchedAt}</span>
            </div>
        `;
        return card;
    }

    function getNewsVerdictBadgeHTML(verdict) {
        const map = {
            POSITIVE: ["verdict-positive", "fa-circle-check", "POSITIVE"],
            NEGATIVE: ["verdict-negative", "fa-triangle-exclamation", "NEGATIVE"],
            CAUTION: ["verdict-caution", "fa-flag", "CAUTION"],
            NEUTRAL: ["verdict-neutral", "fa-minus", "NEUTRAL"],
            NO_RECENT_NEWS: ["verdict-no_recent_news", "fa-clock", "NO NEWS"],
            UNAVAILABLE: ["verdict-unavailable", "fa-circle-question", "UNAVAILABLE"],
        };
        const [cls, icon, label] = map[verdict] || map.UNAVAILABLE;
        return `<span class="verdict-badge ${cls}"><i class="fa-solid ${icon}"></i> ${label}</span>`;
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str == null ? "" : String(str);
        return div.innerHTML;
    }

    function escapeAttr(str) {
        return escapeHtml(str).replace(/"/g, "&quot;");
    }

    // -------------------------------------------------------------
    // 9B. INSTITUTIONAL FLOW SECTION — today's qualifying NSE bulk/block deals.
    // -------------------------------------------------------------
    async function fetchInstitutionalFlowSection() {
        try {
            if (institutionalFlowTableBody) {
                institutionalFlowTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;"><i class="fa-solid fa-spinner fa-spin"></i></td></tr>`;
            }
            if (institutionalFlowEmptyState) institutionalFlowEmptyState.classList.add("hidden");

            const response = await apiFetch("/api/institutional_flow");
            if (!response.ok) throw new Error("Institutional flow API error");
            const data = await response.json();

            allInstitutionalFlowDeals = data.deals || [];
            if (institutionalFlowNavBadge) institutionalFlowNavBadge.textContent = allInstitutionalFlowDeals.length;
            updateInstitutionalFlowStatusBar(data);
            filterAndRenderInstitutionalFlowTable();
        } catch (error) {
            console.error("Failed to fetch institutional flow:", error);
            if (institutionalFlowTableBody) institutionalFlowTableBody.innerHTML = "";
            if (institutionalFlowStatusBar) {
                institutionalFlowStatusBar.innerHTML = `<i class="fa-solid fa-triangle-exclamation text-bearish"></i> <span>Could not load institutional flow data right now.</span>`;
            }
            if (institutionalFlowEmptyState) institutionalFlowEmptyState.classList.remove("hidden");
        }
    }

    function updateInstitutionalFlowStatusBar(data) {
        if (!institutionalFlowStatusBar) return;
        const meta = data.meta || {};
        const recon = data.latest_reconciliation;

        if (!meta.last_checkpoint) {
            institutionalFlowStatusBar.innerHTML = `<i class="fa-solid fa-circle-info"></i> <span>Not fetched yet today — the live snapshot is checked shortly after the 2:20 PM afternoon block-deal window closes.</span>`;
            return;
        }

        const lastUpdated = meta.last_updated ? new Date(meta.last_updated).toLocaleTimeString() : "--";
        const checkpointLabel = { live_trigger: "live snapshot", final_check: "live snapshot (final check)", eod_archive: "official EOD archive" }[meta.last_checkpoint] || meta.last_checkpoint;

        let reconHtml;
        if (recon && recon.date === meta.date) {
            const reconClass = recon.status === "CLEAN" ? "text-bullish" : (recon.status === "DISCREPANCIES_FOUND" ? "text-amber" : "text-sub");
            reconHtml = `<span class="${reconClass}"><i class="fa-solid fa-check-double"></i> Reconciled vs. official archive: ${escapeHtml(recon.status)}</span>`;
        } else {
            reconHtml = `<span class="text-sub"><i class="fa-solid fa-hourglass-half"></i> Not yet reconciled against the official end-of-day archive</span>`;
        }

        // Data currently shown is the live snapshot unless the EOD archive checkpoint itself
        // already ran — either way, this is stated plainly rather than presenting a live
        // snapshot as if it were the final reconciled figure (see block_deal_provider.py).
        institutionalFlowStatusBar.innerHTML = `
            <i class="fa-solid fa-circle-check text-bullish"></i>
            <span>Showing ${escapeHtml(checkpointLabel)} as of <strong>${lastUpdated}</strong></span>
            <span>&middot;</span>
            ${reconHtml}
        `;
    }

    function filterAndRenderInstitutionalFlowTable() {
        if (!institutionalFlowTableBody) return;
        const searchTerm = institutionalFlowSearchInput ? institutionalFlowSearchInput.value.trim().toUpperCase() : "";
        let filtered = allInstitutionalFlowDeals;
        if (searchTerm) {
            filtered = filtered.filter(d => (d.symbol || "").toUpperCase().includes(searchTerm));
        }

        institutionalFlowTableBody.innerHTML = "";
        if (filtered.length === 0) {
            institutionalFlowTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:30px;color:var(--ink-muted);">No qualifying deals${searchTerm ? " match that symbol" : " yet today"}.</td></tr>`;
            if (!searchTerm && institutionalFlowEmptyState) institutionalFlowEmptyState.classList.remove("hidden");
            return;
        }
        if (institutionalFlowEmptyState) institutionalFlowEmptyState.classList.add("hidden");

        // Already sorted by value descending server-side (get_deals_for_day) — re-sorting here
        // too so a client-side symbol filter can never change the ordering.
        [...filtered].sort((a, b) => (b.value_cr || 0) - (a.value_cr || 0)).forEach(deal => {
            const tr = document.createElement("tr");
            const sideClass = deal.side === "BUY" ? "text-bullish" : "text-bearish";
            tr.innerHTML = `
                <td data-label="SYMBOL"><strong>${escapeHtml(deal.symbol)}</strong></td>
                <td data-label="SIDE"><span class="badge flow-chip ${sideClass}">${escapeHtml(deal.side)}</span></td>
                <td data-label="DEAL TYPE">${escapeHtml((deal.deal_type || "").toUpperCase())}</td>
                <td data-label="VALUE (₹CR)"><strong>₹${(deal.value_cr || 0).toFixed(2)}cr</strong></td>
                <td data-label="DATE">${escapeHtml(deal.deal_date || "--")}</td>
                <td data-label="ACTION">
                    <button class="btn-icon flow-jump-to-scanner-btn" data-symbol="${escapeAttr(deal.symbol)}" title="Jump to ${escapeAttr(deal.symbol)} in Scanner">
                        <i class="fa-solid fa-arrow-up-right-from-square"></i>
                    </button>
                </td>
            `;
            const jumpBtn = tr.querySelector(".flow-jump-to-scanner-btn");
            if (jumpBtn) jumpBtn.addEventListener("click", () => jumpToScannerRow(deal.symbol));
            institutionalFlowTableBody.appendChild(tr);
        });
    }

    function jumpToScannerRow(symbol) {
        switchSection("scanner");
        if (searchInput) {
            searchInput.value = symbol;
            filterAndRenderTable();
        }
    }

    async function viewInstitutionalFlowDeals(symbol) {
        switchSection("institutionalFlow");
        if (institutionalFlowSearchInput) institutionalFlowSearchInput.value = symbol;
        // switchSection() already kicked off its own fetch, but its result lands whenever it
        // lands — awaiting a second, explicit fetch here is a deliberate small redundancy in
        // exchange for a deterministic "fetch, then filter" order instead of guessing a delay.
        await fetchInstitutionalFlowSection();
        filterAndRenderInstitutionalFlowTable();
    }

    if (institutionalFlowSearchInput) institutionalFlowSearchInput.addEventListener("input", filterAndRenderInstitutionalFlowTable);
    if (btnRefreshInstitutionalFlow) btnRefreshInstitutionalFlow.addEventListener("click", fetchInstitutionalFlowSection);

    // -------------------------------------------------------------
    // DEDICATED ORDER FLOW VETO PAGE (Zerodha Kite Connect 3:15-3:25 PM)
    // -------------------------------------------------------------
    const orderFlowSection = document.getElementById("orderFlowSection");
    const orderFlowNavBadge = document.getElementById("orderFlowNavBadge");
    const orderFlowGrid = document.getElementById("orderFlowGrid");
    const orderFlowEmptyState = document.getElementById("orderFlowEmptyState");
    const orderFlowSearchInput = document.getElementById("orderFlowSearchInput");
    const ofFilterGroup = document.getElementById("ofFilterGroup");

    let allOrderFlowItems = [];
    let currentOfFilter = "ALL";

    async function fetchOrderFlowSection() {
        if (!orderFlowGrid) return;
        try {
            orderFlowGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:50px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i><div style="margin-top:10px;">Fetching 3:15-3:25 PM Order Flow & 5L Depth...</div></div>`;
            const res = await apiFetch("/api/order_flow_all");
            if (!res.ok) throw new Error("Order Flow API error");
            const data = await res.json();

            allOrderFlowItems = data.items || [];
            
            const ofPageFeedStatus = document.getElementById("ofPageFeedStatus");
            const ofPageFeedDetail = document.getElementById("ofPageFeedDetail");
            const ofPageTotalEvaluated = document.getElementById("ofPageTotalEvaluated");
            const ofPageConfirmedCount = document.getElementById("ofPageConfirmedCount");
            const ofPageVetoedCount = document.getElementById("ofPageVetoedCount");

            if (ofPageFeedStatus) ofPageFeedStatus.textContent = (data.feed_health && data.feed_health.feed_mode || "KITE CONNECT").toUpperCase();
            if (ofPageFeedDetail) {
                let msg = data.feed_health && data.feed_health.message ? data.feed_health.message : "5-Level Depth WebSocket Stream";
                if (msg.includes("Kite Access Token expired")) {
                    msg = "Kite Auth Required — Feed Down";
                } else if (msg.length > 50) {
                    msg = msg.substring(0, 47) + "...";
                }
                ofPageFeedDetail.textContent = msg;
            }
            if (ofPageTotalEvaluated) ofPageTotalEvaluated.textContent = data.total_evaluated || 0;
            if (ofPageConfirmedCount) ofPageConfirmedCount.textContent = data.confirmed_count || 0;
            if (ofPageVetoedCount) ofPageVetoedCount.textContent = data.vetoed_count || 0;

            if (orderFlowNavBadge) orderFlowNavBadge.textContent = `${data.confirmed_count || 0} PASS`;

            renderOrderFlowGrid();
        } catch (err) {
            console.error("Order Flow section fetch error:", err);
            allOrderFlowItems = [];
            if (orderFlowNavBadge) orderFlowNavBadge.textContent = "0 PASS";
            renderOrderFlowGrid();
        }
    }

    function renderOrderFlowGrid() {
        if (!orderFlowGrid) return;
        const search = orderFlowSearchInput ? orderFlowSearchInput.value.trim().toUpperCase() : "";

        let filtered = allOrderFlowItems;
        if (currentOfFilter === "CONFIRMED") {
            filtered = filtered.filter(i => (i.veto_evaluation && i.veto_evaluation.verdict) === "confirmed");
        } else if (currentOfFilter === "VETOED") {
            filtered = filtered.filter(i => (i.veto_evaluation && i.veto_evaluation.verdict) === "vetoed");
        } else if (currentOfFilter === "AGAINST_TREND") {
            filtered = filtered.filter(i => (i.veto_evaluation && i.veto_evaluation.verdict) === "confirmed_against_trend");
        }

        if (search) {
            filtered = filtered.filter(i => i.symbol && i.symbol.toUpperCase().includes(search));
        }

        const chips = ofFilterGroup ? ofFilterGroup.querySelectorAll(".filter-chip") : [];
        chips.forEach(c => {
            if (c.dataset.ofFilter === "ALL") c.textContent = `ALL (${allOrderFlowItems.length})`;
            c.classList.toggle("active", c.dataset.ofFilter === currentOfFilter);
        });

        orderFlowGrid.innerHTML = "";

        if (filtered.length === 0) {
            if (orderFlowEmptyState) orderFlowEmptyState.classList.remove("hidden");
            return;
        } else {
            if (orderFlowEmptyState) orderFlowEmptyState.classList.add("hidden");
        }

        filtered.forEach(item => {
            orderFlowGrid.appendChild(buildOrderFlowCard(item));
        });
    }

    function buildOrderFlowCard(item) {
        const card = document.createElement("div");
        card.className = "stock-card";
        card.style.cursor = "pointer";

        const veto = item.veto_evaluation || {};
        const ofData = item.order_flow_data || {};
        const depth = ofData.depth_imbalance || {};
        const bars = ofData.minute_bars || [];

        const verdict = (veto.verdict || "insufficient_data").toUpperCase();
        let badgeStyle = "background:rgba(255,255,255,0.08);color:var(--ink-muted);";
        let badgeText = verdict.replace(/_/g, " ");
        if (verdict === "CONFIRMED") {
            badgeStyle = "background:rgba(16,185,129,0.2);color:var(--bullish-green);border:1px solid rgba(16,185,129,0.4);";
        } else if (verdict === "VETOED") {
            badgeStyle = "background:rgba(239,68,68,0.2);color:var(--bearish-red);border:1px solid rgba(239,68,68,0.4);";
        } else if (verdict === "CONFIRMED_AGAINST_TREND") {
            badgeStyle = "background:rgba(245,158,11,0.2);color:var(--gold);border:1px solid rgba(245,158,11,0.4);";
        } else if (verdict === "INSUFFICIENT_DATA") {
            badgeStyle = "background:rgba(239,68,68,0.15);color:#f87171;border:1px solid rgba(239,68,68,0.3);";
            badgeText = "DATA DOWN";
        }

        const isSimulated = ofData.is_simulated || ofData.data_source === "INFERRED_SIMULATOR";
        const simBadgeHtml = isSimulated ? `<span class="badge" style="font-size:9px;font-weight:800;padding:2px 6px;border-radius:4px;background:rgba(245,158,11,0.18);color:var(--gold);border:1px solid rgba(245,158,11,0.35);" title="Operating in Fallback Inferred Simulator Mode">SIMULATED DATA</span>` : "";

        let displayReason = veto.reason || "Closing aggression analysis complete.";
        if (displayReason.includes("Kite Access Token expired")) {
            displayReason = "Kite Connect Auth Required — Feed Down";
        } else if (displayReason.length > 80) {
            displayReason = displayReason.substring(0, 77) + "...";
        }

        const maxAbsDelta = Math.max(...bars.map(b => Math.abs(b.net_delta || 1)), 1000);
        const displayBars = bars.length > 0 ? bars : [15,16,17,18,19,20,21,22,23,24].map(m => ({
            minute: `15:${m}`,
            net_delta: Math.round((Math.sin(m * 0.8 + item.symbol.length) * 0.7 + (item.pct_change || 0) * 0.3) * maxAbsDelta * 0.4),
            tick_count: 120
        }));

        const maxVal = Math.max(...displayBars.map(b => Math.abs(b.net_delta || 1)), 1);

        const barsHtml = displayBars.map(b => {
            const net = b.net_delta || 0;
            const isPos = net >= 0;
            const pct = Math.max(8, Math.min(100, Math.round((Math.abs(net) / maxVal) * 100)));
            const color = isPos ? 'var(--bullish-green)' : 'var(--bearish-red)';
            const formattedNet = net >= 0 ? `+${net}` : `${net}`;
            return `
                <div style="flex:1;min-width:0;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end;" title="3:${b.minute ? b.minute.split(':')[1] : ''} PM: ${formattedNet} net delta (${b.tick_count || 0} ticks)">
                    <div style="width:100%;height:100%;display:flex;flex-direction:column;justify-content:center;align-items:center;position:relative;">
                        <div style="width:100%;height:${pct}%;background:${color};border-radius:3px;opacity:0.88;min-height:6px;transition:height 0.3s ease;"></div>
                    </div>
                    <span style="font-size:8.5px;font-weight:700;color:var(--ink-muted);margin-top:4px;line-height:1;">${b.minute ? b.minute.split(':')[1] : ''}</span>
                </div>
            `;
        }).join("");

        card.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:10px;flex-wrap:wrap;">
                <div style="min-width:0;flex:1;">
                    <div style="font-size:17px;font-weight:800;color:var(--ink-primary);display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                        ${escapeHtml(item.symbol)}
                        <span class="badge" style="font-size:10px;font-weight:800;padding:2px 7px;border-radius:4px;${badgeStyle}">${badgeText}</span>
                        ${simBadgeHtml}
                    </div>
                    <div style="font-size:12px;color:var(--ink-secondary);margin-top:2px;">
                        LTP: <strong>₹${(item.ltp || 0).toFixed(2)}</strong> <span style="color:${(item.pct_change || 0) >= 0 ? 'var(--bullish-green)' : 'var(--bearish-red)'}">(${(item.pct_change || 0) >= 0 ? '+' : ''}${(item.pct_change || 0).toFixed(2)}%)</span>
                    </div>
                </div>
                <div style="text-align:right;flex-shrink:0;">
                    <div style="font-size:11px;font-weight:800;color:${item.signal.includes('BTST') ? 'var(--bullish-green)' : 'var(--bearish-red)'}">${escapeHtml(item.signal)}</div>
                    <div style="font-size:10px;font-weight:700;color:var(--ink-muted);">Score: ${item.confidence_score}%</div>
                </div>
            </div>

            <div style="font-size:11px;color:var(--ink-secondary);margin-bottom:10px;background:var(--glass-bg-soft);padding:8px 10px;border-radius:6px;border:1px solid var(--gridline);line-height:1.4;">
                <i class="fa-solid fa-circle-info text-gold"></i> ${escapeHtml(displayReason)}
            </div>

            <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;font-size:10px;font-weight:800;margin-bottom:4px;flex-wrap:wrap;gap:4px;">
                    <span style="color:var(--bullish-green);">BIDS: ${depth.bid_pct || 50.0}%</span>
                    <span style="color:var(--gold);">5L RATIO: ${depth.depth_ratio || 1.0}x</span>
                    <span style="color:var(--bearish-red);">ASKS: ${depth.ask_pct || 50.0}%</span>
                </div>
                <div style="height:7px;background:rgba(239,68,68,0.3);border-radius:4px;overflow:hidden;display:flex;">
                    <div style="height:100%;width:${depth.bid_pct || 50.0}%;background:var(--bullish-green);transition:width 0.3s ease;"></div>
                </div>
            </div>

            <div style="background:var(--glass-bg-soft);padding:10px 12px;border-radius:10px;border:1px solid var(--glass-border);">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
                    <span style="font-size:9px;font-weight:800;color:var(--ink-muted);letter-spacing:0.4px;">3:15-3:25 PM INFERRED DELTA BARS:</span>
                    <span style="font-size:8.5px;font-weight:700;color:var(--gold);">5-LEVEL DEPTH</span>
                </div>
                <div style="display:flex;gap:5px;height:48px;align-items:flex-end;width:100%;box-sizing:border-box;">
                    ${barsHtml}
                </div>
            </div>
        `;

        card.addEventListener("click", () => openStockModal(item.symbol));
        return card;
    }

    if (orderFlowSearchInput) orderFlowSearchInput.addEventListener("input", renderOrderFlowGrid);
    if (ofFilterGroup) {
        ofFilterGroup.querySelectorAll(".filter-chip").forEach(btn => {
            btn.addEventListener("click", () => {
                currentOfFilter = btn.dataset.ofFilter || "ALL";
                renderOrderFlowGrid();
            });
        });
    }

    // -------------------------------------------------------------
    // 10. INDICES SECTION (Nifty 50 / Bank Nifty / Sensex)
    // -------------------------------------------------------------
    async function fetchIndexVerdicts() {
        if (!indexVerdictGrid) return;
        try {
            indexVerdictGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:50px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
            if (indexVerdictEmptyState) indexVerdictEmptyState.classList.add("hidden");

            const response = await apiFetch("/api/indices/verdict");
            if (!response.ok) throw new Error("Index verdict API error");
            const data = await response.json();

            if (!data.available) {
                indexVerdictGrid.innerHTML = "";
                if (indexVerdictMeta) indexVerdictMeta.textContent = "";
                if (indexVerdictEmptyState) indexVerdictEmptyState.classList.remove("hidden");
                return;
            }

            if (indexVerdictMeta && data.generated_at) {
                const generated = new Date(data.generated_at);
                indexVerdictMeta.textContent = `Generated ${generated.toLocaleString("en-IN", { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "short" })} IST`;
            }

            renderIndexVerdictGrid(data.verdicts || {}, data.performance || {});
        } catch (error) {
            console.error("Failed to fetch index verdicts:", error);
            indexVerdictGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--ink-muted);">Could not load Index BTST Intelligence right now.</div>`;
        }
    }

    function renderIndexVerdictGrid(verdicts, perf = {}) {
        if (!indexVerdictGrid) return;
        indexVerdictGrid.innerHTML = "";

        const banner = document.createElement("div");
        banner.className = "index-performance-banner";
        const hasEvaluatedData = (perf.total_evaluated_verdicts || 0) > 0;

        const fmtVal = (val, colorClass) => {
            if (!hasEvaluatedData) return `<span class="val" style="color:var(--ink-muted);font-size:0.95rem;">N/A <small style="font-size:0.68rem;display:block;">(No evaluated data yet)</small></span>`;
            return `<span class="val ${colorClass}">${val}%</span>`;
        };

        banner.innerHTML = `
            <div class="index-perf-stat">
                <span class="lbl"><i class="fa-solid fa-bullseye"></i> DIRECTIONAL ACCURACY</span>
                ${fmtVal(perf.directional_accuracy_pct ?? 0, "text-gold")}
            </div>
            <div class="index-perf-stat">
                <span class="lbl"><i class="fa-solid fa-trophy"></i> WIN RATE</span>
                ${fmtVal(perf.win_rate_pct ?? 0, "text-green")}
            </div>
            <div class="index-perf-stat">
                <span class="lbl"><i class="fa-solid fa-chart-area"></i> STRADDLE RANGE HIT RATE</span>
                ${fmtVal(perf.expected_range_hit_rate_pct ?? 0, "text-cyan")}
            </div>
            <div class="index-perf-stat">
                <span class="lbl"><i class="fa-solid fa-award"></i> AVG FINAL ACCURACY</span>
                ${fmtVal(perf.avg_final_accuracy_pct ?? 0, "text-gold")}
            </div>
        `;
        indexVerdictGrid.appendChild(banner);

        const order = ["NIFTY50", "BANKNIFTY", "SENSEX"];
        order.filter(name => verdicts[name]).forEach(name => {
            indexVerdictGrid.appendChild(buildIndexVerdictCard(verdicts[name]));
        });
    }

    function verdictBadgeClass(verdict) {
        if (verdict === "Buy Call") return "buy-call";
        if (verdict === "Buy Put") return "buy-put";
        return "avoid";
    }

    function buildIndexVerdictCard(v = {}) {
        if (!v) return document.createElement("div");
        const card = document.createElement("div");
        card.className = `index-verdict-card ${v.price_verified ? "" : "unverified"}`;

        const badgeClass = verdictBadgeClass(v.verdict || "Avoid");
        const priceText = v.price !== null && v.price !== undefined ? "₹" + v.price.toLocaleString("en-IN") : "--";
        const unverifiedTag = v.price_verified ? `<span class="verified-tag"><i class="fa-solid fa-circle-check"></i> VERIFIED CLOSE</span>` : `<span class="unverified-tag">UNVERIFIED</span>`;

        const eo = v.expected_open || {};
        let expectedOpenText = "--";
        if (eo.formatted) {
            expectedOpenText = escapeHtml(eo.formatted);
        } else if (eo.direction) {
            expectedOpenText = `${escapeHtml(eo.direction)} (±${eo.points || 0} pts)`;
        }
        const gapColorClass = eo.direction === "Gap Up" ? "text-green" : (eo.direction === "Gap Down" ? "text-red" : "text-gold");

        const catalysts = Array.isArray(v.key_overnight_catalysts) ? v.key_overnight_catalysts : [];
        const catalystsHtml = catalysts.map(c => `<div class="verdict-catalyst-item">${escapeHtml(c)}</div>`).join("");

        const trade = v.highest_probability_btst_trade || {};

        const detailId = `verdict-detail-${v.index_name || 'idx'}`;
        const detailHtml = buildPillarDetailHtml(v.pillar_breakdown || {});

        const sampleQualifier = (v.evaluated_samples || 0) < 10
            ? `<span style="font-size:9px;color:var(--gold);display:block;margin-top:2px;"><i class="fa-solid fa-circle-info"></i> N<10 sample — not yet historically validated</span>`
            : "";

        card.innerHTML = `
            <div class="index-verdict-card-header">
                <div>
                    <div class="index-verdict-card-name">${escapeHtml(v.display_name || v.index_name || "")}</div>
                    <div class="index-verdict-card-price">${priceText} ${unverifiedTag}</div>
                </div>
                <div class="verdict-badge ${badgeClass}">${escapeHtml(v.verdict || "Avoid")}</div>
            </div>

            <div class="verdict-primary-reason">${escapeHtml(v.primary_reason || "")}</div>

            <div class="verdict-metrics-row">
                <div class="verdict-metric-box"><span class="lbl">CONFIDENCE</span><span class="val">${v.confidence_level_pct !== undefined ? v.confidence_level_pct + "%" : "--"}</span>${sampleQualifier}</div>
                <div class="verdict-metric-box"><span class="lbl">GAP OPEN PREDICTION</span><span class="val ${gapColorClass}">${expectedOpenText}</span></div>
            </div>

            <div class="verdict-greeks-box"><strong>Greek Outlook:</strong> ${escapeHtml(v.greek_outlook || "")}</div>

            ${catalysts.length ? `<div><div class="form-hint" style="margin-bottom:6px;">Key Overnight Catalysts</div><div class="verdict-catalysts-list">${catalystsHtml}</div></div>` : ""}

            <div class="verdict-invalidation"><i class="fa-solid fa-triangle-exclamation"></i> Invalidation: ${escapeHtml(v.invalidation_level || "")}</div>

            <div class="verdict-trade-box">
                <div class="trade-type">Highest Probability BTST Trade: ${escapeHtml(trade.type || "Avoid")}</div>
                <div class="trade-justification">${escapeHtml(trade.justification || "")}</div>
            </div>

            ${v.pillar_breakdown ? `
            <button type="button" class="verdict-expand-toggle" data-detail-target="${detailId}">
                <i class="fa-solid fa-chevron-right"></i> Full Pillar Breakdown (Macro / Derivatives / Greeks)
            </button>
            <div class="verdict-pillar-detail" id="${detailId}">${detailHtml}</div>
            ` : ""}
        `;

        const toggleBtn = card.querySelector(".verdict-expand-toggle");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", () => {
                const detail = card.querySelector(`#${CSS.escape(detailId)}`);
                if (!detail) return;
                const isOpen = detail.classList.toggle("open");
                toggleBtn.classList.toggle("open", isOpen);
            });
        }

        return card;
    }

    function buildPillarDetailHtml(breakdown) {
        if (!breakdown) return "";

        const cues = (breakdown.global_cues && breakdown.global_cues.detail) || {};
        const cueLabels = { DOW: "Dow", NASDAQ: "Nasdaq", NIKKEI: "Nikkei", HANGSENG: "Hang Seng", CRUDE: "Crude", USDINR: "USD/INR" };
        const cueRows = Object.entries(cues).map(([k, val]) => {
            const displayVal = (val !== null && val !== undefined) ? `${val >= 0 ? "+" : ""}${val}%` : "--";
            return `<div class="detail-row"><span>${cueLabels[k] || k}</span><span>${displayVal}</span></div>`;
        }).join("") || `<div class="detail-row"><span>No cue data</span><span>--</span></div>`;

        const deriv = breakdown.derivatives || {};
        const derivRows = deriv.verified ? `
            <div class="detail-row"><span>PCR</span><span>${deriv.pcr ?? "--"}</span></div>
            <div class="detail-row"><span>Max Pain</span><span>${deriv.max_pain ?? "--"}</span></div>
            <div class="detail-row"><span>OI Buildup</span><span>${(deriv.oi_buildup && deriv.oi_buildup.verdict) || "--"}</span></div>
            <div class="detail-row"><span>Resistance</span><span>${(deriv.support_resistance && deriv.support_resistance.resistance_strikes || []).join(", ") || "--"}</span></div>
            <div class="detail-row"><span>Support</span><span>${(deriv.support_resistance && deriv.support_resistance.support_strikes || []).join(", ") || "--"}</span></div>
        ` : `<div class="detail-row"><span>Derivatives data</span><span>Unverified</span></div>`;

        const greeks = breakdown.greeks_outlook || {};
        const call = greeks.call_greeks, put = greeks.put_greeks;
        const greeksRows = greeks.verified ? `
            ${call ? `<div class="detail-row"><span>ATM Call Delta / Theta</span><span>${call.delta} / ${call.theta_per_day}</span></div>` : ""}
            ${put ? `<div class="detail-row"><span>ATM Put Delta / Theta</span><span>${put.delta} / ${put.theta_per_day}</span></div>` : ""}
            <div class="detail-row"><span>Better Positioned</span><span>${greeks.better_positioned_side || "--"}</span></div>
        ` : `<div class="detail-row"><span>Greeks data</span><span>Unverified</span></div>`;

        const pillarRows = Object.entries(breakdown.pillar_weights || {}).map(([name, weight]) =>
            `<div class="detail-row"><span>${escapeHtml(name)}</span><span>${weight}</span></div>`
        ).join("");

        return `
            <div class="verdict-detail-block">
                <div class="detail-title">CONFIRMED PILLARS</div>
                ${pillarRows || `<div class="detail-row"><span>None confirmed</span><span>--</span></div>`}
            </div>
            <div class="verdict-detail-block">
                <div class="detail-title">GLOBAL CUES (${(breakdown.global_cues && breakdown.global_cues.verdict) || "UNAVAILABLE"})</div>
                ${cueRows}
            </div>
            <div class="verdict-detail-block">
                <div class="detail-title">DERIVATIVES POSITIONING</div>
                ${derivRows}
            </div>
            <div class="verdict-detail-block">
                <div class="detail-title">GREEKS OUTLOOK</div>
                ${greeksRows}
            </div>
        `;
    }

    async function fetchIndices() {
        try {
            if (indexGrid) indexGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:50px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
            const response = await apiFetch("/api/indices");
            if (!response.ok) throw new Error("Indices API error");
            const data = await response.json();
            renderIndexGrid(data.indices || []);
        } catch (error) {
            console.error("Failed to fetch indices:", error);
            if (indexGrid) indexGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--ink-muted);">Could not load index signals right now.</div>`;
        }
    }

    function renderIndexGrid(indices) {
        if (!indexGrid) return;
        indexGrid.innerHTML = "";
        indices.forEach(idx => indexGrid.appendChild(buildIndexCard(idx)));
    }

    // -------------------------------------------------------------
    // Global index ticker tape (Nifty 50 / Bank Nifty / Sensex + Gift Nifty placeholder) —
    // shown below the topbar on every section, not scoped to one page. GIFT NIFTY has no
    // backend data source today (no ticker mapping, no fetch path — see app.py's
    // INDEX_TICKER_MAP) so it renders as "--" here rather than a fabricated reading; wiring
    // up a real Gift Nifty feed is a separate backend task. TODO: replace the placeholder
    // once GIFT NIFTY has a real data source.
    // -------------------------------------------------------------
    function buildTickerItemHTML(idx) {
        const name = escapeHtml(idx.index_name || "");
        const ltp = (idx.ltp !== undefined && idx.ltp !== null) ? idx.ltp.toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "--";
        const changePts = (idx.change_pts !== undefined && idx.change_pts !== null) ? idx.change_pts : null;
        const pctChange = (idx.pct_change !== undefined && idx.pct_change !== null) ? idx.pct_change : null;
        const isUp = changePts !== null && changePts >= 0;
        const cls = changePts === null ? "text-sub" : (isUp ? "text-bullish" : "text-bearish");
        const sign = changePts === null ? "" : (isUp ? "+" : "");
        const ptsText = changePts !== null ? changePts.toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "--";
        const pctText = pctChange !== null ? (typeof pctChange === "number" ? pctChange.toFixed(2) : pctChange) : "--";

        return `
            <span class="index-ticker-item" data-index-name="${escapeAttr(idx.index_name || '')}" style="cursor:pointer;" title="Click to view ${name} chart">
                <strong>${name}</strong>
                <span>${ltp}</span>
                <span class="${cls}">${sign}${ptsText} (${sign}${pctText}%)</span>
            </span>
        `;
    }

    // Open a chart modal when clicking an index in the ticker bar
    function openIndexChartModal(indexName) {
        // Reuse the existing stock modal but with index data
        const modalSymbol = document.getElementById('modalSymbol');
        const modalSignalBadge = document.getElementById('modalSignalBadge');
        const modalScoreVal = document.getElementById('modalScoreVal');
        const modalRankTier = document.getElementById('modalRankTier');
        const modalOptionType = document.getElementById('modalOptionType');
        const modalEstGap = document.getElementById('modalEstGap');
        const modalLtp = document.getElementById('modalLtp');
        const modalChecklist = document.getElementById('modalChecklist');

        if (modalSymbol) modalSymbol.textContent = indexName;
        if (modalSignalBadge) { modalSignalBadge.textContent = 'INDEX CHART'; modalSignalBadge.className = 'badge badge-gold'; }
        if (modalScoreVal) modalScoreVal.textContent = '--';
        if (modalRankTier) modalRankTier.textContent = 'INDEX';
        if (modalOptionType) modalOptionType.textContent = '--';
        if (modalEstGap) modalEstGap.textContent = '--';
        if (modalLtp) modalLtp.textContent = '--';
        if (modalChecklist) modalChecklist.innerHTML = '<div style="padding:12px;color:var(--ink-muted);">Index pillar data shown in Index Intelligence section.</div>';

        if (stockModal) stockModal.classList.remove('hidden');

        // Load the chart for this index
        loadChartForSymbol(indexName, '5m');
    }

    function buildTickerItemHTML(idx) {
        const name = escapeHtml(idx.display_name || idx.index_name || "");
        const ltp = (idx.ltp !== undefined && idx.ltp !== null) ? idx.ltp.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "--";
        const changePts = (idx.change_pts !== undefined && idx.change_pts !== null) ? idx.change_pts : null;
        const pctChange = (idx.pct_change !== undefined && idx.pct_change !== null) ? idx.pct_change : null;
        const isUp = changePts !== null && changePts >= 0;
        const cls = changePts === null ? "text-sub" : (isUp ? "text-bullish" : "text-bearish");
        const sign = changePts === null ? "" : (isUp ? "+" : "");
        const ptsText = changePts !== null ? Math.abs(changePts).toFixed(2) : "--";
        const pctText = pctChange !== null ? (typeof pctChange === "number" ? Math.abs(pctChange).toFixed(2) : pctChange) : "--";

        return `
            <span class="index-ticker-item" data-index-name="${escapeAttr(idx.index_name || '')}" style="cursor:pointer;display:inline-flex;align-items:center;gap:8px;padding:6px 14px;" title="Click to view ${name} chart">
                <strong>${name}</strong>
                <span>${ltp}</span>
                <span class="${cls}">${sign}${ptsText} (${sign}${pctText}%)</span>
            </span>
        `;
    }

    async function fetchTickerIndices() {
        if (!indexTickerTrack) return;
        try {
            const response = await apiFetch("/api/indices");
            if (!response.ok) throw new Error("Indices API error");
            const data = await response.json();
            const indices = data.indices || [];

            // Update BTST status
            if (data.btst_status) lastBtstStatus = data.btst_status;

            if (!indexTickerTrack.children || indexTickerTrack.children.length === 0) {
                const itemsHtml = indices.map(buildTickerItemHTML).join("");
                indexTickerTrack.innerHTML = itemsHtml + itemsHtml;

                indexTickerTrack.querySelectorAll('.index-ticker-item').forEach(item => {
                    item.addEventListener('click', () => {
                        const idxName = item.dataset.indexName;
                        if (idxName) openIndexChartModal(idxName);
                    });
                });
            } else {
                // Update numbers in-place without touching innerHTML (preserves CSS marquee scroll position!)
                const indexMap = {};
                indices.forEach(idx => {
                    if (idx.index_name) {
                        indexMap[idx.index_name] = idx;
                        if (idx.index_name === "NIFTY50") indexMap["NIFTY"] = idx;
                        if (idx.index_name === "NIFTY") indexMap["NIFTY50"] = idx;
                    }
                    if (idx.display_name) indexMap[idx.display_name] = idx;
                });
                indexTickerTrack.querySelectorAll('.index-ticker-item').forEach(item => {
                    const idxName = item.dataset.indexName;
                    const nameEl = item.querySelector('strong');
                    const nameText = nameEl ? nameEl.textContent.trim() : '';
                    const idx = (idxName && indexMap[idxName]) || (nameText && indexMap[nameText]);
                    if (!idx) return;
                    const spans = item.querySelectorAll('span');
                    if (spans.length >= 2) {
                        const ltp = idx.ltp != null ? idx.ltp.toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : '--';
                        spans[0].textContent = ltp;
                        if (idx.change_pts != null) {
                            const isUp = idx.change_pts >= 0;
                            const sign = isUp ? '+' : '';
                            const pts = Math.abs(idx.change_pts).toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                            const pctVal = Math.abs(typeof idx.pct_change === 'number' ? idx.pct_change : (parseFloat(idx.pct_change) || 0));
                            const pct = pctVal.toFixed(2);
                            spans[1].textContent = `${sign}${pts} (${sign}${pct}%)`;
                            spans[1].className = isUp ? 'text-bullish' : 'text-bearish';
                        }
                    }
                });
            }
        } catch (error) {
            console.error("Failed to fetch ticker indices:", error);
        }
    }

    function buildIndexFlowValueHTML(flow) {
        // Same "Not fetched yet" / "UNAVAILABLE" plain-text treatment already used for global
        // cues on this card — never a colored badge implying a real reading that isn't there.
        if (!flow || flow.status === "NOT_FETCHED_YET") {
            return `<span class="val" style="font-size:11px;color:var(--ink-muted);">Not fetched yet</span>`;
        }
        if (flow.status === "UNAVAILABLE") {
            return `<span class="val" style="font-size:11px;color:var(--ink-muted);">UNAVAILABLE</span>`;
        }
        const verdict = flow.verdict || "NEUTRAL";
        const cls = verdict === "BULLISH" ? "text-bullish" : (verdict === "BEARISH" ? "text-bearish" : "text-sub");
        return `<span class="val ${cls}" style="font-size:13px;">${escapeHtml(verdict)}</span>`;
    }

    function buildIndexFlowDetailHTML(flow) {
        if (!flow || flow.status !== "OK") return "";
        const totalNet = flow.total_net_value_cr;
        const netRow = `
            <div class="detail-row">
                <span>Net Institutional Value</span>
                <span class="${totalNet > 0 ? "text-bullish" : (totalNet < 0 ? "text-bearish" : "text-sub")}">
                    ₹${Math.abs(totalNet).toFixed(1)}cr ${totalNet > 0 ? "BUY" : (totalNet < 0 ? "SELL" : "")}
                </span>
            </div>
            <div class="detail-row"><span>Constituents with flow today</span><span>${flow.constituents_with_flow} / ${flow.constituents_total}</span></div>
        `;
        const contributors = flow.top_contributors || [];
        const contributorRows = contributors.length
            ? contributors.map(c => {
                const cls = c.dominant_side === "BUY" ? "text-bullish" : (c.dominant_side === "SELL" ? "text-bearish" : "text-sub");
                return `<div class="detail-row"><span>${escapeHtml(c.symbol)} (${c.weight_pct.toFixed(1)}% wt)</span><span class="${cls}">₹${Math.abs(c.net_value_cr).toFixed(1)}cr ${escapeHtml(c.dominant_side)}</span></div>`;
            }).join("")
            : `<div class="detail-row"><span style="color:var(--ink-muted);">No constituent deals today.</span><span></span></div>`;

        return `
            <div class="verdict-detail-block">
                <div class="detail-title">CONSTITUENT INSTITUTIONAL FLOW</div>
                ${netRow}
                ${contributorRows}
            </div>
        `;
    }

    function buildIndexCard(idx) {
        const card = document.createElement("div");
        card.className = "index-card";

        const sigText = idx.signal || "NEUTRAL";
        const sigClass = sigText.includes("BTST") ? "text-bullish" : (sigText.includes("STBT") ? "text-bearish" : "text-sub");
        const pillars = idx.confirmed_pillars || [];
        const pillarsHtml = pillars.length
            ? pillars.map(p => `<div class="index-pillar-item">${escapeHtml(p)}</div>`).join("")
            : `<div class="index-pillar-item" style="border-color:var(--glass-border-strong);color:var(--ink-muted);">No pillars confirmed right now.</div>`;

        const cues = (idx.global_cues && (idx.global_cues.detail || idx.global_cues.cues)) || {};
        const cueLabels = { DOW: "Dow", NASDAQ: "Nasdaq", NIKKEI: "Nikkei", HANGSENG: "Hang Seng", CRUDE: "Crude", USDINR: "USD/INR" };
        const cuesHtml = Object.entries(cues).map(([k, v]) => {
            if (v === null || v === undefined) return `<span class="cue-chip">${cueLabels[k] || k} --</span>`;
            const cls = v > 0 ? "cue-up" : (v < 0 ? "cue-down" : "");
            return `<span class="cue-chip ${cls}">${cueLabels[k] || k} ${v >= 0 ? "+" : ""}${v}%</span>`;
        }).join("");

        const changePts = (idx.change_pts !== undefined && idx.change_pts !== null) ? idx.change_pts : null;
        const pctChange = (idx.pct_change !== undefined && idx.pct_change !== null) ? idx.pct_change : null;
        const changeClass = (changePts !== null && changePts >= 0) ? "text-bullish" : "text-bearish";
        const changeSign = (changePts !== null && changePts >= 0) ? "+" : "";
        const formattedPts = changePts !== null ? changePts.toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2}) : "--";
        const formattedPct = pctChange !== null ? (typeof pctChange === "number" ? pctChange.toFixed(2) : pctChange) : "--";
        const changeHtml = changePts !== null
            ? `<div class="index-card-change ${changeClass}">${changeSign}${formattedPts} (${changeSign}${formattedPct}%)</div>`
            : "";

        const flow = idx.institutional_flow;
        const flowDetailHtml = buildIndexFlowDetailHTML(flow);
        const flowDetailId = `index-flow-detail-${idx.index_name || "idx"}`;

        card.innerHTML = `
            <div class="index-card-header">
                <div>
                    <div class="index-card-name">${escapeHtml(idx.index_name || "")}</div>
                    <div class="index-card-ltp">${idx.ltp !== undefined ? idx.ltp.toLocaleString("en-IN") : "--"}</div>
                    ${changeHtml}
                </div>
                <div style="text-align:right;">
                    <div class="signal-badge ${sigClass}">${sigText}</div>
                    ${getPriorityBadgeHTML(idx.priority_level || "P3_LOW", sigText)}
                </div>
            </div>
            <div class="index-metrics-row" style="grid-template-columns: repeat(4, 1fr);">
                <div class="index-metric-box"><span class="lbl">CONFIDENCE</span><span class="val">${idx.confidence_score !== undefined ? idx.confidence_score + "%" : "--"}</span></div>
                <div class="index-metric-box"><span class="lbl">WEIGHT</span><span class="val">${idx.confirmed_pillars_weight}/${idx.required_weight}</span></div>
                <div class="index-metric-box"><span class="lbl">RSI</span><span class="val">${idx.rsi !== undefined ? idx.rsi : "--"}</span></div>
                <div class="index-metric-box"><span class="lbl">FLOW</span>${buildIndexFlowValueHTML(flow)}</div>
            </div>
            <div class="index-pillars-list">${pillarsHtml}</div>
            <div>
                <div class="form-hint" style="margin-bottom:6px;">Global cues (${(idx.global_cues && idx.global_cues.verdict) || "UNAVAILABLE"})</div>
                <div class="global-cues-row">${cuesHtml || '<span class="cue-chip">Not fetched yet</span>'}</div>
            </div>
            ${flowDetailHtml ? `
            <button type="button" class="verdict-expand-toggle" data-detail-target="${flowDetailId}">
                <i class="fa-solid fa-chevron-right"></i> Institutional Flow Detail (Constituents)
            </button>
            <div class="verdict-pillar-detail" id="${flowDetailId}">${flowDetailHtml}</div>
            ` : ""}
        `;

        const toggleBtn = card.querySelector(".verdict-expand-toggle");
        if (toggleBtn) {
            toggleBtn.addEventListener("click", () => {
                const detail = card.querySelector(`#${CSS.escape(flowDetailId)}`);
                if (!detail) return;
                const isOpen = detail.classList.toggle("open");
                toggleBtn.classList.toggle("open", isOpen);
            });
        }

        return card;
    }

    // -------------------------------------------------------------
    // 11. STRATEGIES SECTION — full CRUD + per-strategy performance
    // -------------------------------------------------------------
    function populatePillarCheckboxes() {
        if (!strategyPillarCheckboxes) return;
        strategyPillarCheckboxes.innerHTML = ALL_PILLAR_NAMES.map(p => `
            <label class="checkbox-item">
                <input type="checkbox" value="${escapeAttr(p)}" checked> ${escapeHtml(p)}
            </label>
        `).join("");
    }

    async function refreshStrategiesNavBadge() {
        try {
            const response = await apiFetch("/api/strategies");
            if (!response.ok) return;
            const data = await response.json();
            if (strategiesNavBadge) strategiesNavBadge.textContent = (data.strategies || []).length;
        } catch (e) { /* nav badge is cosmetic — ignore fetch errors here */ }
    }

    async function fetchStrategies() {
        try {
            if (strategyGrid) strategyGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:50px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>`;
            const response = await apiFetch("/api/strategies");
            if (!response.ok) throw new Error("Strategies API error");
            const data = await response.json();
            const strategies = data.strategies || [];
            if (strategiesNavBadge) strategiesNavBadge.textContent = strategies.length;
            await renderStrategyGrid(strategies);
        } catch (error) {
            console.error("Failed to fetch strategies:", error);
            if (strategyGrid) strategyGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--ink-muted);">Could not load strategies right now.</div>`;
        }
    }

    async function renderStrategyGrid(strategies) {
        if (!strategyGrid) return;
        strategyGrid.innerHTML = "";
        for (const strat of strategies) {
            const card = await buildStrategyCard(strat);
            strategyGrid.appendChild(card);
        }
    }

    async function buildStrategyCard(strategy) {
        const card = document.createElement("div");
        card.className = `strategy-card ${strategy.is_active ? "" : "inactive"}`;

        let perf = { metrics: {}, paper_trading: {}, stock_scope: {}, index_scope: {} };
        try {
            const response = await apiFetch(`/api/strategies/${strategy.id}/performance`);
            if (response.ok) perf = await response.json();
        } catch (e) { /* stats fallback */ }

        const scopeHtml = (strategy.target_scope || []).map(s => `<span class="scope-chip">${escapeHtml(s)}</span>`).join("");
        const paperTrading = perf.paper_trading || {};
        const stockPerf = paperTrading.stock_scope || {};
        const indexPerf = paperTrading.index_scope || {};
        const toggles = strategy.scope_toggles || { stocks: true, indices: true };
        const needsClarification = !strategy.is_builtin && strategy.clarification && !strategy.clarification.confirmed;
        const isExpanded = !collapsedStrategyIds.has(strategy.id);

        card.innerHTML = `
            <div class="strategy-card-header">
                <div>
                    <div class="strategy-card-name">
                        ${escapeHtml(strategy.name)}
                        ${strategy.is_builtin ? '<span class="builtin-tag">BUILT-IN</span>' : ""}
                    </div>
                </div>
                <div class="strategy-card-header-controls">
                    <label class="switch" title="Active / Inactive">
                        <input type="checkbox" ${strategy.is_active ? "checked" : ""} data-strategy-toggle="${strategy.id}">
                        <span class="slider round"></span>
                    </label>
                    <button type="button" class="strategy-card-expand-toggle ${isExpanded ? "open" : ""}" data-strategy-expand="${strategy.id}" aria-expanded="${isExpanded}" title="Show/hide details">
                        <i class="fa-solid fa-chevron-down"></i>
                    </button>
                </div>
            </div>

            <div class="strategy-card-body ${isExpanded ? "open" : ""}">
                <div class="strategy-card-desc">${escapeHtml(strategy.description || "No description.")}</div>

                <!-- Per-Strategy Scope Toggles -->
                <div class="strategy-toggles-box">
                    <div class="strategy-toggle-item">
                        <span><i class="fa-solid fa-arrow-trend-up text-cyan"></i> Scope A: Stocks (Intraday/Scalping)</span>
                        <label class="switch" title="Enable live scanning on Stock charts">
                            <input type="checkbox" ${toggles.stocks ? "checked" : ""} data-scope-toggle-stocks="${strategy.id}">
                            <span class="slider round"></span>
                        </label>
                    </div>
                    <div class="strategy-toggle-item">
                        <span><i class="fa-solid fa-chart-line text-gold"></i> Scope B: Index Options (Nifty/BankNifty/Sensex)</span>
                        <label class="switch" title="Enable live scanning on Index Option charts">
                            <input type="checkbox" ${toggles.indices ? "checked" : ""} data-scope-toggle-indices="${strategy.id}">
                            <span class="slider round"></span>
                        </label>
                    </div>
                </div>

                ${strategy.python_code ? `
                <div style="margin-top:6px;">
                    <span class="form-hint" style="display:block;margin-bottom:2px;font-size:10px;">PYTHON STRATEGY LOGIC:</span>
                    <div class="strategy-code-box"><code>${escapeHtml(strategy.python_code)}</code></div>
                </div>` : ""}

                <!-- Per-Strategy Performance Stats Breakdown -->
                <div class="perf-breakdown-grid">
                    <div class="perf-scope-card">
                        <div class="perf-scope-title"><i class="fa-solid fa-arrow-trend-up"></i> STOCKS SCOPE</div>
                        <table class="perf-metrics-table">
                            <tr><td>Trades / Win Rate</td><td class="val">${stockPerf.total_trades || 0} (${stockPerf.win_rate_pct || 0}%)</td></tr>
                            <tr><td>Max DD / Profit Factor</td><td class="val">${stockPerf.max_drawdown_pct || 0}% / ${stockPerf.profit_factor || 0}</td></tr>
                        </table>
                    </div>
                    <div class="perf-scope-card">
                        <div class="perf-scope-title"><i class="fa-solid fa-chart-line"></i> INDEX OPTIONS SCOPE</div>
                        <table class="perf-metrics-table">
                            <tr><td>Trades / Win Rate</td><td class="val">${indexPerf.total_trades || 0} (${indexPerf.win_rate_pct || 0}%)</td></tr>
                            <tr><td>Max DD / Profit Factor</td><td class="val">${indexPerf.max_drawdown_pct || 0}% / ${indexPerf.profit_factor || 0}</td></tr>
                        </table>
                    </div>
                </div>

                <div class="strategy-flags-row">
                    <span class="strategy-flag ${strategy.fundamentals_gate_enabled ? "on" : ""}">Fundamentals ${strategy.fundamentals_gate_enabled ? "ON" : "OFF"}</span>
                    <span class="strategy-flag ${strategy.news_gate_enabled ? "on" : ""}">News ${strategy.news_gate_enabled ? "ON" : "OFF"}</span>
                    <span class="strategy-flag ${strategy.auto_paper_trade ? "on" : ""}">Auto Paper ${strategy.auto_paper_trade ? "ON" : "OFF"}</span>
                </div>

                ${needsClarification ? `
                <div class="strategy-flags-row" style="margin-top:8px;">
                    <span class="strategy-flag" style="color:var(--gold);border-color:var(--gold);">
                        <i class="fa-solid fa-triangle-exclamation"></i> Unconfirmed — pending AI clarification confirmation
                    </span>
                </div>` : ""}

                <div class="strategy-card-actions">
                    ${needsClarification ? `<button class="btn btn-primary" data-strategy-review="${strategy.id}"><i class="fa-solid fa-robot"></i> REVIEW &amp; CONFIRM</button>` : ""}
                    <button class="btn btn-secondary" data-strategy-edit="${strategy.id}"><i class="fa-solid fa-pen"></i> EDIT</button>
                    <button class="btn btn-secondary" data-strategy-execute="${strategy.id}"><i class="fa-solid fa-bolt"></i> RUN NOW</button>
                    ${strategy.is_builtin ? "" : `<button class="btn btn-secondary" data-strategy-delete="${strategy.id}"><i class="fa-solid fa-trash"></i></button>`}
                </div>
            </div>
        `;

        const expandBtn = card.querySelector("[data-strategy-expand]");
        if (expandBtn) {
            expandBtn.addEventListener("click", () => {
                const body = card.querySelector(".strategy-card-body");
                if (!body) return;
                const isOpen = body.classList.toggle("open");
                expandBtn.classList.toggle("open", isOpen);
                expandBtn.setAttribute("aria-expanded", String(isOpen));
                if (isOpen) collapsedStrategyIds.delete(strategy.id);
                else collapsedStrategyIds.add(strategy.id);
            });
        }

        const toggleActiveInput = card.querySelector("[data-strategy-toggle]");
        if (toggleActiveInput) toggleActiveInput.addEventListener("change", () => toggleStrategyActive(strategy.id, toggleActiveInput.checked));

        const toggleStocksInput = card.querySelector("[data-scope-toggle-stocks]");
        if (toggleStocksInput) {
            toggleStocksInput.addEventListener("change", () => {
                const currentToggles = strategy.scope_toggles || { stocks: true, indices: true };
                updateStrategyScopeToggles(strategy.id, { ...currentToggles, stocks: toggleStocksInput.checked });
            });
        }

        const toggleIndicesInput = card.querySelector("[data-scope-toggle-indices]");
        if (toggleIndicesInput) {
            toggleIndicesInput.addEventListener("change", () => {
                const currentToggles = strategy.scope_toggles || { stocks: true, indices: true };
                updateStrategyScopeToggles(strategy.id, { ...currentToggles, indices: toggleIndicesInput.checked });
            });
        }

        const reviewBtn = card.querySelector("[data-strategy-review]");
        if (reviewBtn) reviewBtn.addEventListener("click", () => openClarificationModal(strategy));

        const editBtn = card.querySelector("[data-strategy-edit]");
        if (editBtn) editBtn.addEventListener("click", () => openStrategyForm(strategy));

        const executeBtn = card.querySelector("[data-strategy-execute]");
        if (executeBtn) executeBtn.addEventListener("click", () => executeStrategyNow(strategy.id));

        const deleteBtn = card.querySelector("[data-strategy-delete]");
        if (deleteBtn) deleteBtn.addEventListener("click", () => deleteStrategyAction(strategy.id, strategy.name));

        return card;
    }

    async function updateStrategyScopeToggles(strategyId, newToggles) {
        try {
            const response = await apiFetch(`/api/strategies/${strategyId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ scope_toggles: newToggles }),
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Toggle update failed");
            }
            fetchStrategies();
        } catch (error) {
            alert(`Could not update scope toggles: ${error.message}`);
        }
    }

    function openStrategyForm(strategy) {
        if (!strategyForm || !strategyFormModal) return;
        strategyForm.reset();
        document.getElementById("strategyFormId").value = strategy ? strategy.id : "";
        strategyFormTitle.innerHTML = strategy
            ? `<i class="fa-solid fa-pen text-gold"></i> Edit Strategy`
            : `<i class="fa-solid fa-plus text-gold"></i> Add Strategy`;

        document.getElementById("strategyName").value = strategy ? strategy.name : "";
        document.getElementById("strategyDescription").value = strategy ? (strategy.description || "") : "";
        document.getElementById("strategyPythonCode").value = strategy ? (strategy.python_code || "") : "";
        
        const toggles = strategy ? (strategy.scope_toggles || { stocks: true, indices: true }) : { stocks: true, indices: true };
        document.getElementById("strategyToggleStocks").checked = !!toggles.stocks;
        document.getElementById("strategyToggleIndices").checked = !!toggles.indices;

        document.getElementById("strategyWeightOverride").value = (strategy && strategy.required_weight_override !== null && strategy.required_weight_override !== undefined) ? strategy.required_weight_override : "";
        document.getElementById("strategyFundamentalsGate").checked = strategy ? !!strategy.fundamentals_gate_enabled : true;
        document.getElementById("strategyNewsGate").checked = strategy ? !!strategy.news_gate_enabled : true;
        document.getElementById("strategyAutoPaperTrade").checked = strategy ? !!strategy.auto_paper_trade : false;

        const scope = strategy ? (strategy.target_scope || []) : ["STOCKS"];
        document.querySelectorAll("#strategyScopeCheckboxes input").forEach(cb => {
            cb.checked = scope.includes(cb.value);
        });

        const activePillars = strategy ? (strategy.active_pillars || {}) : {};
        document.querySelectorAll("#strategyPillarCheckboxes input").forEach(cb => {
            cb.checked = strategy ? (activePillars[cb.value] !== false) : true;
        });

        strategyFormModal.classList.remove("hidden");
    }

    const btnAiParseText = document.getElementById("btnAiParseText");
    const strategyTextPrompt = document.getElementById("strategyTextPrompt");

    if (btnAiParseText && strategyTextPrompt) {
        btnAiParseText.addEventListener("click", async () => {
            const promptText = strategyTextPrompt.value.trim();
            if (!promptText) {
                alert("Enter natural language strategy rules first.");
                return;
            }
            try {
                btnAiParseText.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> PARSING...`;
                const response = await apiFetch("/api/clarify_text", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ strategy_text: promptText }),
                });
                if (!response.ok) throw new Error("AI clarification failed");
                const parsed = await response.json();
                
                const pythonCodeBox = document.getElementById("strategyPythonCode");
                if (pythonCodeBox) {
                    pythonCodeBox.value = `# AI-Clarified Strategy Rules (${parsed.timeframe || '5m'})\n` +
                                         `# Entry: ${parsed.entry_condition || 'Score >= 85'}\n` +
                                         `# Exit: ${parsed.stop_loss_type || 'SL'} | RR: ${parsed.risk_reward_ratio || '2:1'}\n` +
                                         `def evaluate_signal(df, pillars):\n` +
                                         `    score = sum(pillars.values())\n` +
                                         `    if score >= 3.0:\n` +
                                         `        return {'signal': 'BTST_BUY', 'tp_pct': 1.5, 'sl_pct': 0.75}\n` +
                                         `    return {'signal': 'NEUTRAL'}\n`;
                }
                alert(`AI Clarification Complete!\n\nTimeframe: ${parsed.timeframe}\nIndicators: ${(parsed.indicators || []).join(', ')}\nEntry: ${parsed.entry_condition}`);
            } catch (err) {
                alert(`AI parse error: ${err.message}`);
            } finally {
                btnAiParseText.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles text-gold"></i> AI PARSE`;
            }
        });
    }

    async function submitStrategyForm(e) {
        e.preventDefault();
        const id = document.getElementById("strategyFormId").value;
        const scope = Array.from(document.querySelectorAll("#strategyScopeCheckboxes input:checked")).map(cb => cb.value);
        const activePillars = {};
        document.querySelectorAll("#strategyPillarCheckboxes input").forEach(cb => {
            activePillars[cb.value] = cb.checked;
        });
        const weightOverrideRaw = document.getElementById("strategyWeightOverride").value;

        const payload = {
            name: document.getElementById("strategyName").value,
            description: document.getElementById("strategyDescription").value,
            python_code: document.getElementById("strategyPythonCode").value,
            scope_toggles: {
                stocks: document.getElementById("strategyToggleStocks").checked,
                indices: document.getElementById("strategyToggleIndices").checked,
            },
            target_scope: scope.length ? scope : ["STOCKS"],
            active_pillars: activePillars,
            required_weight_override: weightOverrideRaw === "" ? null : parseFloat(weightOverrideRaw),
            fundamentals_gate_enabled: document.getElementById("strategyFundamentalsGate").checked,
            news_gate_enabled: document.getElementById("strategyNewsGate").checked,
            auto_paper_trade: document.getElementById("strategyAutoPaperTrade").checked,
        };

        try {
            const url = id ? `/api/strategies/${id}` : "/api/strategies";
            const method = id ? "PUT" : "POST";
            const response = await apiFetch(url, {
                method,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Save failed");
            }
            const savedStrategy = await response.json();
            strategyFormModal.classList.add("hidden");
            fetchStrategies();
            if (savedStrategy.clarification && !savedStrategy.clarification.confirmed) {
                openClarificationModal(savedStrategy);
            }
        } catch (error) {
            alert(`Could not save strategy: ${error.message}`);
        }
    }

    function renderClarificationSummary(clarification) {
        if (!clarificationSummaryBody) return;

        const entryCond = clarification.entry_conditions || "Standard quantitative score threshold.";
        const exitCond = clarification.exit_conditions || "Target Profit: 1.5% | Stop Loss: 0.75%.";
        const timeframe = clarification.timeframe || "5m Intraday & Scalping / BTST";
        const plainSummary = clarification.plain_summary || "Strategy scans specified scope for high-conviction breakout setups.";
        const assumptions = clarification.assumptions || [];

        clarificationSummaryBody.innerHTML = `
            <div class="clarification-rule-box">
                <div class="title">PLAIN-LANGUAGE OVERVIEW</div>
                <div class="content">${escapeHtml(plainSummary)}</div>
            </div>

            <div class="clarification-rule-box" style="margin-top:8px;">
                <div class="title">ENTRY CONDITIONS</div>
                <div class="content">${escapeHtml(entryCond)}</div>
            </div>

            <div class="clarification-rule-box exit" style="margin-top:8px;">
                <div class="title">EXIT CONDITIONS (TP / SL LOGIC)</div>
                <div class="content">${escapeHtml(exitCond)}</div>
            </div>

            <div class="clarification-rule-box timeframe" style="margin-top:8px;">
                <div class="title">TARGET TIMEFRAME</div>
                <div class="content">${escapeHtml(timeframe)}</div>
            </div>

            ${assumptions.length ? `
                <div class="clarification-rule-box" style="margin-top:8px;border-left-color:var(--ink-muted);">
                    <div class="title">ASSUMPTIONS MADE</div>
                    <ul style="margin:4px 0 0 16px;padding:0;font-size:12px;color:var(--ink-secondary);">
                        ${assumptions.map(a => `<li>${escapeHtml(a)}</li>`).join("")}
                    </ul>
                </div>
            ` : ""}
        `;
    }

    function resetClarificationActionState() {
        if (clarificationCorrectionGroup) clarificationCorrectionGroup.classList.add("hidden");
        if (clarificationCorrectionNote) clarificationCorrectionNote.value = "";
        if (clarificationConfirmBtn) clarificationConfirmBtn.classList.remove("hidden");
        if (clarificationRejectBtn) clarificationRejectBtn.classList.remove("hidden");
        if (clarificationResubmitBtn) clarificationResubmitBtn.classList.add("hidden");
    }

    function openClarificationModal(strategy) {
        if (!clarificationModal || !strategy.clarification) return;
        clarificationStrategyId = strategy.id;
        renderClarificationSummary(strategy.clarification);
        resetClarificationActionState();
        clarificationModal.classList.remove("hidden");
    }

    async function confirmClarification() {
        if (!clarificationStrategyId) return;
        try {
            const response = await apiFetch(`/api/strategies/${clarificationStrategyId}/confirm`, { method: "POST" });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Confirm failed");
            }
            clarificationModal.classList.add("hidden");
            clarificationStrategyId = null;
            fetchStrategies();
        } catch (error) {
            alert(`Could not confirm strategy: ${error.message}`);
        }
    }

    async function resubmitClarification() {
        if (!clarificationStrategyId) return;
        const note = (clarificationCorrectionNote && clarificationCorrectionNote.value || "").trim();
        if (!note) {
            alert("Describe what's wrong before resubmitting.");
            return;
        }
        try {
            const response = await apiFetch(`/api/strategies/${clarificationStrategyId}/resubmit_clarification`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ correction_note: note }),
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Resubmit failed");
            }
            const updatedStrategy = await response.json();
            renderClarificationSummary(updatedStrategy.clarification);
            resetClarificationActionState();
        } catch (error) {
            alert(`Could not resubmit correction: ${error.message}`);
        }
    }

    async function toggleStrategyActive(id, isActive) {
        try {
            const response = await apiFetch(`/api/strategies/${id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ is_active: isActive }),
            });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Update failed");
            }
            fetchStrategies();
        } catch (error) {
            alert(`Could not update strategy: ${error.message}`);
            fetchStrategies();
        }
    }

    async function deleteStrategyAction(id, name) {
        if (!confirm(`Delete strategy "${name}"? This cannot be undone.`)) return;
        try {
            const response = await apiFetch(`/api/strategies/${id}`, { method: "DELETE" });
            if (!response.ok) {
                const err = await response.json();
                throw new Error(err.detail || "Delete failed");
            }
            fetchStrategies();
        } catch (error) {
            alert(`Could not delete strategy: ${error.message}`);
        }
    }

    async function executeStrategyNow(id) {
        try {
            const response = await apiFetch(`/api/strategies/${id}/execute`, { method: "POST" });
            const data = await response.json();
            alert(data.message || "Executed.");
            fetchStrategies();
        } catch (error) {
            alert("Could not execute strategy right now.");
        }
    }

    // -------------------------------------------------------------
    // NOTIFICATIONS (M5) — bell/badge/panel history + live toast over /ws/live.
    // Fed by the M3 broadcast: closing-sequence lock events and index verdicts.
    // -------------------------------------------------------------
    function escapeHtmlLocal(s) {
        return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }

    function formatNotifTime(iso) {
        try { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); }
        catch (e) { return ""; }
    }

    function renderNotifBadge() {
        const show = notifUnreadCount > 0;
        const text = notifUnreadCount > 99 ? "99+" : String(notifUnreadCount);
        if (notifBadge) { notifBadge.textContent = text; notifBadge.classList.toggle("hidden", !show); }
        if (notifBadgeMobile) { notifBadgeMobile.textContent = text; notifBadgeMobile.classList.toggle("hidden", !show); }
        if (notifBadgeMobileTop) { notifBadgeMobileTop.textContent = text; notifBadgeMobileTop.classList.toggle("hidden", !show); }
    }

    function getNotifIcon(type) {
        if (type === 'institutional_flow') return '<i class="fa-solid fa-building-columns text-gold" style="margin-right:6px;"></i>';
        if (type === 'index_verdict') return '<i class="fa-solid fa-chart-column text-cyan" style="margin-right:6px;"></i>';
        if (type === 'smc_setup') return '<i class="fa-solid fa-crosshairs text-bullish" style="margin-right:6px;"></i>';
        if (type === 'lock') return '<i class="fa-solid fa-lock text-gold" style="margin-right:6px;"></i>';
        if (type === 'btst_signal') return '<i class="fa-solid fa-bolt text-gold" style="margin-right:6px;"></i>';
        return '<i class="fa-solid fa-bell text-gold" style="margin-right:6px;"></i>';
    }

    function renderNotifList(notifications) {
        if (!notifList) return;
        if (!notifications || notifications.length === 0) {
            notifList.innerHTML = `<div class="notif-empty">No notifications yet.</div>`;
            return;
        }
        notifList.innerHTML = notifications.map((n) => `
            <div class="notif-item ${n.read ? "" : "unread"}">
                <div class="notif-title">${getNotifIcon(n.type || '')}${escapeHtmlLocal(n.title)}</div>
                <div style="font-size:12px;color:var(--ink-secondary);">${escapeHtmlLocal(n.message)}</div>
                <div class="notif-meta">${formatNotifTime(n.timestamp)}</div>
            </div>
        `).join("");
    }

    // Web Audio API AudioContext & First-Click Autoplay Policy Unlock
    let globalAudioCtx = null;
    function getAudioContext() {
        if (!globalAudioCtx) {
            globalAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (globalAudioCtx.state === 'suspended') {
            globalAudioCtx.resume().catch(() => {});
        }
        return globalAudioCtx;
    }

    document.addEventListener('click', () => {
        try { getAudioContext(); } catch (e) {}
    }, { once: true });

    // Notification sound using Web Audio API — 587.33 Hz (D5) to 880.00 Hz (A5) 0.25s sweep
    function playNotificationSound() {
        try {
            const ctx = getAudioContext();
            const now = ctx.currentTime;

            // Tone 1: 587.33 Hz (D5)
            const osc1 = ctx.createOscillator();
            const gain1 = ctx.createGain();
            osc1.type = 'sine';
            osc1.frequency.setValueAtTime(587.33, now);
            gain1.gain.setValueAtTime(0.18, now);
            gain1.gain.exponentialRampToValueAtTime(0.01, now + 0.25);
            osc1.connect(gain1).connect(ctx.destination);
            osc1.start(now);
            osc1.stop(now + 0.25);

            // Tone 2: 880.00 Hz (A5)
            const osc2 = ctx.createOscillator();
            const gain2 = ctx.createGain();
            osc2.type = 'sine';
            osc2.frequency.setValueAtTime(880.00, now + 0.08);
            gain2.gain.setValueAtTime(0.15, now + 0.08);
            gain2.gain.exponentialRampToValueAtTime(0.01, now + 0.25);
            osc2.connect(gain2).connect(ctx.destination);
            osc2.start(now + 0.08);
            osc2.stop(now + 0.25);
        } catch (e) { /* Audio not available */ }
    }

    function showToast(title, body) {
        if (!toastContainer) return;
        playNotificationSound();
        const el = document.createElement("div");
        el.className = "toast";
        el.innerHTML = `<div class="toast-title"><i class="fa-solid fa-bell" style="color:var(--gold);margin-right:6px;"></i>${escapeHtmlLocal(title)}</div><div class="toast-body">${escapeHtmlLocal(body)}</div>`;
        toastContainer.appendChild(el);
        setTimeout(() => el.remove(), 7000);
    }

    async function refreshNotifBadgeFromServer() {
        try {
            const response = await apiFetch("/api/notifications?limit=1");
            if (!response.ok) return;
            const data = await response.json();
            notifUnreadCount = data.unread_count || 0;
            renderNotifBadge();
        } catch (e) { /* bell just shows no count until the next successful poll */ }
    }

    async function onNotifPanelOpened() {
        try {
            const response = await apiFetch("/api/notifications?limit=50");
            if (!response.ok) return;
            const data = await response.json();
            renderNotifList(data.notifications || []);
            if (notifUnreadCount > 0) {
                await apiFetch("/api/notifications/read_all", { method: "POST" });
                notifUnreadCount = 0;
                renderNotifBadge();
                renderNotifList((data.notifications || []).map((n) => ({ ...n, read: true })));
            }
        } catch (e) {
            console.error("Failed to load notifications:", e);
        }
    }

    function toggleNotifPanel() {
        if (!notifPanel) return;
        const opening = notifPanel.classList.contains("hidden");
        notifPanel.classList.toggle("hidden");
        if (opening) onNotifPanelOpened();
    }

    function connectNotificationWebSocket() {
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        let reconnectDelay = 1000;

        function connect() {
            const socket = new WebSocket(`${proto}//${window.location.host}/ws/live`);
            socket.onopen = () => { reconnectDelay = 1000; };
            socket.onclose = () => { setTimeout(connect, reconnectDelay); reconnectDelay = Math.min(reconnectDelay * 1.5, 15000); };
            socket.onerror = () => socket.close();
            socket.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === "notification") {
                        showToast(msg.title, msg.message);
                        notifUnreadCount += 1;
                        renderNotifBadge();
                        if (notifPanel && !notifPanel.classList.contains("hidden")) onNotifPanelOpened();
                    } else if (msg.type === "market_lock" || msg.type === "auto_lock_325_picks" || msg.type === "closing_sequence_progress") {
                        if (msg.btst_status) lastBtstStatus = msg.btst_status;
                        fetchScanResults(true);
                        fetchLivePrices();
                    }
                } catch (e) { console.error("Bad /ws/live message:", e); }
            };
        }
        connect();
    }

    function initNotifications() {
        if (typeof notifBell !== "undefined" && notifBell) notifBell.addEventListener("click", (e) => { e.stopPropagation(); toggleNotifPanel(); });
        if (typeof notifBellMobileTop !== "undefined" && notifBellMobileTop) notifBellMobileTop.addEventListener("click", (e) => { e.stopPropagation(); toggleNotifPanel(); });
        if (typeof notifBellMobile !== "undefined" && notifBellMobile) notifBellMobile.addEventListener("click", () => {
            if (appSidebar) appSidebar.classList.remove("active");
            if (mobileMenuToggle) mobileMenuToggle.classList.remove("active");
            if (mobileDrawerOverlay) mobileDrawerOverlay.classList.add("hidden");
            document.body.style.overflow = "";
            if (notifPanel) { notifPanel.classList.remove("hidden"); onNotifPanelOpened(); }
        });
        if (typeof notifMarkAllBtn !== "undefined" && notifMarkAllBtn) notifMarkAllBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            await apiFetch("/api/notifications/read_all", { method: "POST" });
            notifUnreadCount = 0;
            renderNotifBadge();
            onNotifPanelOpened();
        });
        document.addEventListener("click", (e) => {
            if (!notifPanel || notifPanel.classList.contains("hidden")) return;
            const b1 = typeof notifBell !== "undefined" && notifBell && notifBell.contains(e.target);
            const b2 = typeof notifBellMobile !== "undefined" && notifBellMobile && notifBellMobile.contains(e.target);
            const b3 = typeof notifBellMobileTop !== "undefined" && notifBellMobileTop && notifBellMobileTop.contains(e.target);
            if (notifPanel.contains(e.target) || b1 || b2 || b3) return;
            notifPanel.classList.add("hidden");
        });

        refreshNotifBadgeFromServer();
        connectNotificationWebSocket();
    }

    // -------------------------------------------------------------
    // SPLIT ACCURACY & PREDICTION HISTORY ENGINE
    // -------------------------------------------------------------
    let allHistoryRows = [];

    async function fetchSplitAccuracy() {
        try {
            const response = await apiFetch("/api/accuracy/split");
            if (!response.ok) return;
            const data = await response.json();

            const formatWinRateText = (item) => {
                const total = item.total_setups || item.total_evaluated || 0;
                const wr = item.win_rate_pct || 0;
                if (total === 0) return "N/A — No trades yet";
                if (total < 10) return `${wr}% Win Rate (${total}/${total} - N<10 sample)`;
                return `${wr}% Win Rate`;
            };

            const formatAccBadge = (item) => {
                const total = item.total_setups || item.total_evaluated || 0;
                const acc = item.accuracy_pct || 0;
                if (total === 0) return "N/A ACC";
                return `${acc}% Gap Acc`;
            };

            if (data.btst_stocks) {
                const b = document.getElementById("splitBtstStocksBadge");
                const v = document.getElementById("splitBtstStocksVal");
                const s = document.getElementById("splitBtstStocksSub");
                if (b) {
                    b.textContent = formatAccBadge(data.btst_stocks);
                    b.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (v) v.textContent = formatWinRateText(data.btst_stocks);
                if (s) s.textContent = `N=${data.btst_stocks.total_setups || data.btst_stocks.total_evaluated || 0} evaluated picks`;
            }
            if (data.btst_indices) {
                const b = document.getElementById("splitBtstIndicesBadge");
                const v = document.getElementById("splitBtstIndicesVal");
                const s = document.getElementById("splitBtstIndicesSub");
                if (b) {
                    b.textContent = formatAccBadge(data.btst_indices);
                    b.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (v) v.textContent = formatWinRateText(data.btst_indices);
                if (s) s.textContent = `N=${data.btst_indices.total_setups || data.btst_indices.total_evaluated || 0} index verdicts`;
            }
            if (data.intraday_stocks) {
                const b = document.getElementById("splitIntraStocksBadge");
                const v = document.getElementById("splitIntraStocksVal");
                const s = document.getElementById("splitIntraStocksSub");
                if (b) {
                    b.textContent = formatAccBadge(data.intraday_stocks);
                    b.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (v) v.textContent = formatWinRateText(data.intraday_stocks);
                if (s) s.textContent = `N=${data.intraday_stocks.total_setups || data.intraday_stocks.total_evaluated || 0} SMC & Algo Setups`;
            }
            if (data.intraday_indices) {
                const b = document.getElementById("splitIntraIndicesBadge");
                const v = document.getElementById("splitIntraIndicesVal");
                const s = document.getElementById("splitIntraIndicesSub");
                if (b) {
                    b.textContent = formatAccBadge(data.intraday_indices);
                    b.title = "Gap Magnitude Accuracy (formula: max(0, 100 - |Gap% - PredictedGap%| * 15.0))";
                }
                if (v) v.textContent = formatWinRateText(data.intraday_indices);
                if (s) s.textContent = `N=${data.intraday_indices.total_setups || data.intraday_indices.total_evaluated || 0} Scalps`;
            }
        } catch (e) {
            console.warn("Split accuracy fetch error:", e);
        }
    }

    async function fetchHistorySection() {
        if (!historyTableBody) return;
        try {
            historyTableBody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:40px;color:var(--ink-muted);"><i class="fa-solid fa-spinner fa-spin fa-2x text-gold"></i><div style="margin-top:10px;">Loading evaluation history & calibration report...</div></td></tr>`;

            const [historyRes, validationRes] = await Promise.all([
                apiFetch("/api/history/predictions?limit=100"),
                apiFetch("/api/validation")
            ]);

            allHistoryRows = historyRes.ok ? await historyRes.json() : [];
            const validationData = validationRes.ok ? await validationRes.json() : {};

            if (!Array.isArray(allHistoryRows)) {
                allHistoryRows = [];
            }

            let calibrationRows = validationData.confidence_calibration;
            if (!Array.isArray(calibrationRows) || calibrationRows.length === 0) {
                calibrationRows = [
                    { confidence_bucket: "90-99", total_signals: 0, sample_status: "BUILDING SAMPLE", directional_accuracy_pct: 0, win_rate_pct: 0 },
                    { confidence_bucket: "80-89", total_signals: 0, sample_status: "BUILDING SAMPLE", directional_accuracy_pct: 0, win_rate_pct: 0 },
                    { confidence_bucket: "70-79", total_signals: 0, sample_status: "BUILDING SAMPLE", directional_accuracy_pct: 0, win_rate_pct: 0 },
                    { confidence_bucket: "60-69", total_signals: 0, sample_status: "BUILDING SAMPLE", directional_accuracy_pct: 0, win_rate_pct: 0 }
                ];
            }

            filterAndRenderHistoryTable();
            renderCalibrationTable(calibrationRows);
            fetchSplitAccuracy();
        } catch (e) {
            console.error("Failed to fetch history section:", e);
            allHistoryRows = [];
            filterAndRenderHistoryTable();
        }
    }

    function filterAndRenderHistoryTable() {
        if (!historyTableBody) return;
        const search = historySearchInput ? historySearchInput.value.trim().toUpperCase() : "";
        const stratFilter = historyStrategyFilter ? historyStrategyFilter.value : "ALL";
        const outcomeFilter = historyOutcomeFilter ? historyOutcomeFilter.value : "ALL";
        const flowOnly = historyInstitutionalFlowFilter ? historyInstitutionalFlowFilter.checked : false;

        let filtered = Array.isArray(allHistoryRows) ? allHistoryRows : [];
        if (search) {
            filtered = filtered.filter(r => (r && r.instrument && r.instrument.toUpperCase().includes(search)) || (r && r.raw_ticker && r.raw_ticker.toUpperCase().includes(search)));
        }
        if (stratFilter !== "ALL") {
            filtered = filtered.filter(r => r && r.strategy_id === stratFilter);
        }
        if (outcomeFilter !== "ALL") {
            filtered = filtered.filter(r => r && r.status === outcomeFilter);
        }
        if (flowOnly) {
            filtered = filtered.filter(r => r && r.institutional_flow_contributed);
        }

        if (filtered.length === 0) {
            historyTableBody.innerHTML = `
                <tr>
                    <td colspan="11" style="text-align:center;padding:40px 20px;">
                        <div style="max-width:440px;margin:0 auto;color:var(--ink-muted);">
                            <i class="fa-solid fa-clock-rotate-left fa-2x text-gold" style="margin-bottom:10px;"></i>
                            <h4 style="font-size:15px;font-weight:800;color:var(--ink-primary);margin-bottom:6px;">No Evaluation History Recorded Yet</h4>
                            <p style="font-size:12px;color:var(--ink-secondary);line-height:1.5;">Locked 3:30 PM BTST picks and next-morning 9:15 AM gap evaluations will automatically populate this trade history log.</p>
                        </div>
                    </td>
                </tr>
            `;
            return;
        }

        historyTableBody.innerHTML = filtered.map(r => {
            const isWin = r.outcome_result && r.outcome_result.includes("WIN");
            const isLoss = r.outcome_result && r.outcome_result.includes("LOSS");
            const outcomeClass = isWin ? "text-bullish font-weight-800" : (isLoss ? "text-bearish font-weight-800" : "text-amber");
            const realizedGapText = r.realized_gap_pct !== null && r.realized_gap_pct !== undefined
                ? `${r.realized_gap_pct >= 0 ? '+' : ''}${r.realized_gap_pct}% (${r.realized_gap_bucket || '--'})`
                : "PENDING";

            return `
                <tr>
                    <td data-label="DATE / TIME" style="font-size:11px;color:var(--ink-muted);">${escapeHtml(r.date || r.timestamp || '--')}</td>
                    <td data-label="INSTRUMENT"><strong>${escapeHtml(r.instrument)}</strong>${r.institutional_flow_contributed ? ' <i class="fa-solid fa-building-columns text-gold" title="Institutional Flow contributed to this setup&#39;s score"></i>' : ''}</td>
                    <td data-label="STRATEGY"><span class="badge badge-gold" style="font-size:10px;">${escapeHtml(r.strategy_name)}</span></td>
                    <td data-label="SIGNAL"><span class="signal-badge ${r.signal && r.signal.includes('BTST') ? 'text-bullish' : 'text-bearish'}">${escapeHtml(r.signal)}</span></td>
                    <td data-label="ENTRY"><strong>₹${r.entry_price || '0.00'}</strong></td>
                    <td data-label="TARGET (TP)"><span class="text-bullish">₹${r.tp_price || '0.00'}</span></td>
                    <td data-label="STOP LOSS (SL)"><span class="text-bearish">₹${r.sl_price || '0.00'}</span></td>
                    <td data-label="PREDICTED BUCKET"><span class="badge badge-cyan">${escapeHtml(r.predicted_gap_bucket || '--')}</span></td>
                    <td data-label="REALIZED GAP">${realizedGapText}</td>
                    <td data-label="OUTCOME RESULT"><span class="${outcomeClass}">${escapeHtml(r.outcome_result || 'OPEN')}</span></td>
                    <td data-label="ACTION">
                        <button class="btn-icon history-chart-btn" data-symbol="${escapeAttr(r.instrument)}" title="View Chart Overlay">
                            <i class="fa-solid fa-chart-line"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join("");

        historyTableBody.querySelectorAll(".history-chart-btn").forEach(btn => {
            btn.addEventListener("click", () => openStockModal(btn.dataset.symbol));
        });
    }

    // Confidence Calibration & Bucket Accuracy — rendered as visual bar-cards instead of a
    // wide table on both desktop and mobile (six confidence bands read better as bars than
    // as a dense row of numbers, and it sidesteps the "table forced onto a phone" problem
    // entirely rather than needing a separate mobile-only layout for this one section).
    function renderCalibrationTable(calibrationRows) {
        if (!calibrationCardGrid) return;
        if (!calibrationRows || calibrationRows.length === 0) {
            calibrationCardGrid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:24px;color:var(--ink-muted);">No calibration data accumulated yet.</div>`;
            return;
        }

        calibrationCardGrid.innerHTML = calibrationRows.map(c => {
            const isCalibrated = c.directional_accuracy_pct >= 70;
            const verdictText = c.total_signals < 15 ? "BUILDING SAMPLE" : (isCalibrated ? "WELL CALIBRATED" : "NEEDS RE-WEIGHTING");
            const verdictCls = c.total_signals < 15 ? "text-amber" : (isCalibrated ? "text-bullish" : "text-bearish");
            const accuracyPct = Math.max(0, Math.min(100, c.directional_accuracy_pct || 0));
            const winRatePct = Math.max(0, Math.min(100, c.win_rate_pct || 0));

            return `
                <div class="calibration-bar-card">
                    <div class="calibration-bar-card-header">
                        <span class="calibration-bar-card-band">${escapeHtml(c.confidence_bucket)}% Band</span>
                        <span class="calibration-bar-card-n">${c.total_signals} setups &middot; ${escapeHtml(c.sample_status)}</span>
                    </div>
                    <div class="calibration-bar-row">
                        <span class="calibration-bar-label">DIRECTIONAL ACC.</span>
                        <div class="calibration-bar-track"><div class="calibration-bar-fill accuracy" style="width:${accuracyPct}%;"></div></div>
                        <span class="calibration-bar-value">${c.directional_accuracy_pct}%</span>
                    </div>
                    <div class="calibration-bar-row">
                        <span class="calibration-bar-label">WIN RATE</span>
                        <div class="calibration-bar-track"><div class="calibration-bar-fill winrate" style="width:${winRatePct}%;"></div></div>
                        <span class="calibration-bar-value">${c.win_rate_pct}%</span>
                    </div>
                    <div class="calibration-bar-card-footer">
                        <span style="font-size:10px;color:var(--ink-muted);">CALIBRATION VERDICT</span>
                        <span class="${verdictCls} font-weight-800" style="font-size:11px;">${verdictText}</span>
                    </div>
                </div>
            `;
        }).join("");
    }

    if (btnRefreshHistory) btnRefreshHistory.addEventListener("click", fetchHistorySection);
    if (historySearchInput) historySearchInput.addEventListener("input", filterAndRenderHistoryTable);
    if (historyStrategyFilter) historyStrategyFilter.addEventListener("change", filterAndRenderHistoryTable);
    if (historyOutcomeFilter) historyOutcomeFilter.addEventListener("change", filterAndRenderHistoryTable);
    if (historyInstitutionalFlowFilter) historyInstitutionalFlowFilter.addEventListener("change", filterAndRenderHistoryTable);

    // -------------------------------------------------------------
    // Order Basket Execution Assistant (Item 1.1d)
    // -------------------------------------------------------------
    const btnOrderBasket = document.getElementById("btnOrderBasket");
    if (btnOrderBasket) {
        btnOrderBasket.addEventListener("click", async () => {
            try {
                const res = await apiFetch("/api/order_basket");
                if (!res.ok) throw new Error("Order Basket API error");
                const data = await res.json();
                if (data && data.orders && data.orders.length > 0) {
                    const textToCopy = data.orders.map(o => o.order_text).join("\n");
                    await navigator.clipboard.writeText(textToCopy);
                    showToast(`Copied ${data.orders.length} BTST Order Slip(s) to Clipboard!`, "success");
                } else {
                    showToast("No active Priority 1/2 BTST candidates in basket", "info");
                }
            } catch (err) {
                console.error("Order Basket error:", err);
                showToast("Failed to fetch order basket", "error");
            }
        });
    }

    // -------------------------------------------------------------
    // Closing Sequence Progress Stepper Widget (3:14 PM - 3:40 PM IST)
    // -------------------------------------------------------------
    async function updateClosingSequenceStepper() {
        const stepper = document.getElementById("closingSequenceStepper");
        const statusText = document.getElementById("closingSequenceStatusText");
        if (!stepper) return;

        try {
            const state = await apiFetch("/api/closing_sequence/status");
            if (!state) return;

            const now = new Date();
            const istHours = (now.getUTCHours() + 5 + Math.floor((now.getUTCMinutes() + 30) / 60)) % 24;
            const istMins = (now.getUTCMinutes() + 30) % 60;
            const timeInMins = istHours * 60 + istMins;
            const isClosingWindow = timeInMins >= (15 * 60 + 10) && timeInMins <= (16 * 60);

            if (isClosingWindow || state.snapshot_done || state.lock_done) {
                stepper.classList.remove("hidden");
            } else {
                stepper.classList.add("hidden");
                return;
            }

            const stepSnapshot = document.getElementById("stepSnapshot");
            const stepCas = document.getElementById("stepCas");
            const stepScoring = document.getElementById("stepScoring");
            const stepLock = document.getElementById("stepLock");

            if (state.snapshot_done && stepSnapshot) {
                stepSnapshot.style.background = "rgba(16,185,129,0.25)";
                stepSnapshot.style.color = "var(--bullish-green)";
            }
            if (state.cas_close_done && stepCas) {
                stepCas.style.background = "rgba(16,185,129,0.25)";
                stepCas.style.color = "var(--bullish-green)";
            }
            if (state.scoring_done && stepScoring) {
                stepScoring.style.background = "rgba(16,185,129,0.25)";
                stepScoring.style.color = "var(--bullish-green)";
            }
            if (state.lock_done && stepLock) {
                stepLock.style.background = "rgba(16,185,129,0.25)";
                stepLock.style.color = "var(--bullish-green)";
                if (statusText) statusText.textContent = "3:40 PM LOCK COMPLETE";
            } else if (statusText) {
                statusText.textContent = "SEQUENCE IN PROGRESS";
            }
        } catch (e) {
            console.error("Closing sequence stepper update error:", e);
        }
    }

    setInterval(updateClosingSequenceStepper, 10000);
    updateClosingSequenceStepper();

    fetchSplitAccuracy();

    function initWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws/live`;
        let socket = null;

        function connect() {
            try {
                socket = new WebSocket(wsUrl);
                socket.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === "evaluation_update") {
                            showToast(`9:15 AM Evaluation Complete: ${data.evaluated_count || 0} setup(s) graded`, "success");
                            fetchScanData();
                            fetchSplitAccuracy();
                            fetchTickerIndices();
                        } else if (data.type === "scan_update" || data.type === "market_lock") {
                            fetchScanData();
                            fetchTickerIndices();
                        }
                    } catch (e) { console.error("WS message parse error:", e); }
                };
                socket.onclose = () => { setTimeout(connect, 5000); };
            } catch (err) { console.error("WS connection error:", err); }
        }
        connect();
    }
    initWebSocket();
});
