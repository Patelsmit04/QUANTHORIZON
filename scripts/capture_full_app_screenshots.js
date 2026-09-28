const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const http = require('http');

async function detectActivePort() {
    const ports = [8001, 8000];
    for (const port of ports) {
        try {
            const ok = await new Promise((resolve) => {
                const req = http.get(`http://127.0.0.1:${port}/`, { timeout: 1500 }, (res) => {
                    resolve(res.statusCode === 200);
                });
                req.on('error', () => resolve(false));
                req.on('timeout', () => { req.destroy(); resolve(false); });
            });
            if (ok) {
                console.log(`[+] Detected active TRADEXO server on port: ${port}`);
                return port;
            }
        } catch (e) {
            // continue
        }
    }
    return 8001;
}

(async () => {
    console.log("===============================================================");
    console.log("  📸 TRADEXO MASTER SCREENSHOT REFRESH SUITE");
    console.log("  Capturing all pages, sub-views, and modals with updated vector logos");
    console.log("===============================================================\n");

    const activePort = await detectActivePort();
    const baseUrl = `http://127.0.0.1:${activePort}`;

    const outDir = path.join(__dirname, '..', 'screenshots_all_features');
    const brainDir = 'C:\\Users\\Smit Patel\\.gemini\\antigravity-ide\\brain\\1a98e442-69f5-4116-b2b3-81fc3745e30d';

    if (!fs.existsSync(outDir)) {
        fs.mkdirSync(outDir, { recursive: true });
    }

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        viewport: { width: 1440, height: 960 },
        deviceScaleFactor: 2
    });

    await context.addInitScript(() => {
        sessionStorage.setItem('hasSeenIntro', 'true');
        sessionStorage.setItem('tradexo_intro_viewed_v3', 'true');
        localStorage.setItem('hasSeenIntro', 'true');
        localStorage.setItem('tradexo_intro_seen', 'true');
        localStorage.setItem('tradexo_theme', 'dark');
        localStorage.setItem('qh-theme', 'dark');
    });

    const page = await context.newPage();

    async function dismissOverlay() {
        await page.evaluate(() => {
            const overlay = document.getElementById('tradexoIntroOverlay');
            if (overlay) {
                overlay.remove();
            }
            const drawerOverlay = document.getElementById('mobileDrawerOverlay');
            if (drawerOverlay && !drawerOverlay.classList.contains('hidden')) {
                drawerOverlay.classList.add('hidden');
            }
            document.body.classList.remove('intro-active');
        });
    }

    async function saveScreenshot(filenames) {
        if (!Array.isArray(filenames)) filenames = [filenames];
        await page.waitForTimeout(500);
        const primary = filenames[0];
        const primaryPath = path.join(outDir, primary);
        await page.screenshot({ path: primaryPath, fullPage: false });
        console.log(`  [OK] Saved: ${primary}`);

        for (let i = 1; i < filenames.length; i++) {
            const targetPath = path.join(outDir, filenames[i]);
            fs.copyFileSync(primaryPath, targetPath);
            console.log(`  [OK] Mirrored to: ${filenames[i]}`);
        }

        if (fs.existsSync(brainDir)) {
            for (const f of filenames) {
                try {
                    fs.copyFileSync(primaryPath, path.join(brainDir, f));
                } catch (e) {}
            }
        }
    }

    async function navTo(sectionId) {
        console.log(`\n>>> Navigating to Section: [${sectionId}]`);
        await page.evaluate((id) => {
            if (typeof window.switchSection === 'function') {
                window.switchSection(id);
            } else {
                const btn = document.querySelector(`.sidebar-nav-item[data-section="${id}"]`);
                if (btn) btn.click();
            }
        }, sectionId);
        await page.waitForTimeout(1000);
        await dismissOverlay();
    }

    try {
        console.log(`Connecting to TRADEXO at ${baseUrl}...`);
        await page.goto(`${baseUrl}/`, { waitUntil: 'domcontentloaded', timeout: 25000 });
        await dismissOverlay();
        await page.waitForTimeout(2000);

        // Wait for scanner data to populate
        await page.waitForFunction(() => {
            return (window.allStocks && window.allStocks.length > 0) ||
                   document.querySelectorAll('#scannerDataTable tbody tr').length > 0;
        }, { timeout: 15000 }).catch(() => console.log('Notice: Scanner table load timed out, proceeding...'));

        await page.waitForTimeout(1000);

        // =================================================================
        // 1. SCANNER / SIGNALS ENGINE
        // =================================================================
        console.log("\n--- SECTION 1: SCANNER & STOCKS ---");
        await navTo('scanner');

        // 01: BTST Stocks Tab (Table view with vector logos)
        await page.evaluate(() => {
            const btn = document.getElementById('stockViewIntelligenceBtn');
            if (btn) btn.click();
        });
        await page.waitForTimeout(1000);
        await saveScreenshot(['01_scanner_btst_stocks.png', '01_scanner_table_logos.png']);

        // Search for RELIANCE row
        await page.fill('#searchInput', 'RELIANCE');
        await page.waitForTimeout(800);
        await saveScreenshot('02_scanner_search_reliance_logo.png');
        await page.fill('#searchInput', '');
        await page.waitForTimeout(600);

        // 02: LIVE Stocks Grid Tab (with company cards and logos)
        await page.evaluate(() => {
            const btn = document.getElementById('stockViewLiveBtn');
            if (btn) btn.click();
        });
        await page.waitForTimeout(1200);
        await saveScreenshot(['02_scanner_live_stocks.png', '04_scanner_live_stocks_logos.png', '03_scanner_grid_logos.png', '04_scanner_grid_logos.png']);

        // 03: Stock Detail Quantitative Analysis Modal (open for RELIANCE)
        console.log("Opening Stock Detail Analysis Modal for RELIANCE...");
        await page.evaluate(async () => {
            if (typeof window.renderStockDetailPage === 'function') {
                await window.renderStockDetailPage('RELIANCE');
            }
            if (typeof window.openStockModal === 'function') {
                await window.openStockModal('RELIANCE', 'analysis');
            }
            if (typeof window.switchSection === 'function') {
                window.switchSection('stockDetail');
            }
        });
        await page.waitForTimeout(1500);
        await saveScreenshot(['03_scanner_stock_detail_analysis_modal.png', '03_stock_detail_modal_reliance_logo.png']);

        // 04: Stock Candlestick Chart View
        await page.evaluate(() => {
            const chartTab = document.getElementById('btnStockDetailChartTab') ||
                             document.getElementById('btnModalChartTab') ||
                             document.querySelector('[data-stock-tab="chart"]');
            if (chartTab) chartTab.click();
        });
        await page.waitForTimeout(1800);
        await saveScreenshot('04_scanner_stock_detail_chart_modal.png');

        // Close Stock Detail / return to scanner
        await page.evaluate(() => {
            const backBtn = document.getElementById('btnBackFromStockDetail');
            if (backBtn) backBtn.click();
            const modal = document.getElementById('stockModal');
            if (modal) modal.classList.add('hidden');
        });
        await page.waitForTimeout(600);

        // =================================================================
        // 2. INDEX INTELLIGENCE
        // =================================================================
        console.log("\n--- SECTION 2: INDEX INTELLIGENCE ---");
        await navTo('indices');

        // 05: BTST Intelligence View
        await page.evaluate(() => {
            const btn = document.querySelector('[data-index-view="intelligence"]') ||
                        document.getElementById('btnIndexViewIntelligence');
            if (btn) btn.click();
        });
        await page.waitForTimeout(1200);
        await saveScreenshot('05_indices_btst_intelligence.png');

        // 06: Live Index Signals View
        await page.evaluate(() => {
            const btn = document.querySelector('[data-index-view="signals"]') ||
                        document.getElementById('btnIndexViewSignals');
            if (btn) btn.click();
        });
        await page.waitForTimeout(1200);
        await saveScreenshot('06_indices_live_index_signals.png');

        // 07: NIFTY Option Chain Modal
        console.log("Opening NIFTY Option Chain Modal...");
        await page.evaluate(async () => {
            if (typeof window.openOptionChainModal === 'function') {
                await window.openOptionChainModal('NIFTY');
            }
        });
        await page.waitForTimeout(1500);
        await saveScreenshot(['07_indices_nifty_option_chain_modal.png', '07_option_chain_nifty.png']);

        // Close Option Chain Modal
        await page.evaluate(() => {
            if (typeof window.closeOptionChainModal === 'function') {
                window.closeOptionChainModal();
            } else {
                const modal = document.getElementById('optionChainModal');
                if (modal) modal.classList.add('hidden');
            }
        });
        await page.waitForTimeout(600);

        // 08: BANKNIFTY Option Chain Modal
        console.log("Opening BANKNIFTY Option Chain Modal...");
        await page.evaluate(async () => {
            if (typeof window.openOptionChainModal === 'function') {
                await window.openOptionChainModal('BANKNIFTY');
            }
        });
        await page.waitForTimeout(1500);
        await saveScreenshot(['08_indices_banknifty_option_chain_modal.png', '08_option_chain_banknifty.png']);

        // Close Option Chain Modal
        await page.evaluate(() => {
            if (typeof window.closeOptionChainModal === 'function') {
                window.closeOptionChainModal();
            } else {
                const modal = document.getElementById('optionChainModal');
                if (modal) modal.classList.add('hidden');
            }
        });
        await page.waitForTimeout(600);

        // =================================================================
        // 3. LIVE TRADE EXECUTION
        // =================================================================
        console.log("\n--- SECTION 3: LIVE TRADES ---");
        await navTo('liveTrades');

        // 09: ALL ACTIVE Tab
        await page.evaluate(() => {
            const tab = document.getElementById('liveTabActive') || document.querySelector('[data-live-tab="active"]');
            if (tab) tab.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot(['09_live_trade_all_active.png', '05_live_trades_logos.png', '04_live_trades_logos.png']);

        // 10: BTST CALLS Tab
        await page.evaluate(() => {
            const tab = document.getElementById('liveTabBtst') || document.querySelector('[data-live-tab="btst"]');
            if (tab) tab.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('10_live_trade_btst_calls.png');

        // 11: STBT PUTS Tab
        await page.evaluate(() => {
            const tab = document.getElementById('liveTabStbt') || document.querySelector('[data-live-tab="stbt"]');
            if (tab) tab.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('11_live_trade_stbt_puts.png');

        // 12: PENDING ORDERS Tab
        await page.evaluate(() => {
            const tab = document.getElementById('liveTabPending') || document.querySelector('[data-live-tab="pending"]');
            if (tab) tab.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('12_live_trade_pending_orders.png');

        // 13: TRADE LOG Tab
        await page.evaluate(() => {
            const tab = document.getElementById('liveTabClosed') || document.querySelector('[data-live-tab="closed"]');
            if (tab) tab.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('13_live_trade_trade_log.png');

        // =================================================================
        // 4. PAPER TRADING PORTFOLIO
        // =================================================================
        console.log("\n--- SECTION 4: PAPER PORTFOLIO ---");
        await navTo('paperTrading');
        await page.waitForTimeout(1000);
        await saveScreenshot('14_paper_portfolio_overview.png');

        // =================================================================
        // 5. STRATEGIES ENGINE
        // =================================================================
        console.log("\n--- SECTION 5: STRATEGIES ENGINE ---");
        await navTo('strategies');
        await page.waitForTimeout(1000);
        await saveScreenshot(['15_strategies_overview.png', '15_phase2_clean_toolbar.png']);

        // Add Strategy Modal
        await page.evaluate(() => {
            const btn = document.getElementById('addStrategyBtn');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('16_strategies_add_strategy_modal.png');

        await page.evaluate(() => {
            const modal = document.getElementById('strategyFormModal');
            if (modal) modal.classList.add('hidden');
        });
        await page.waitForTimeout(500);

        // =================================================================
        // 6. STOCKS NEWS SENTIMENT
        // =================================================================
        console.log("\n--- SECTION 6: STOCKS NEWS ---");
        await navTo('stocksNews');
        await page.waitForTimeout(1000);
        await saveScreenshot(['17_stocks_news_all.png', '17_stocks_news_overview.png']);

        // Positive
        await page.evaluate(() => {
            const btn = document.querySelector('#stocksNewsSection button[data-verdict="POSITIVE"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('18_stocks_news_positive.png');

        // Caution
        await page.evaluate(() => {
            const btn = document.querySelector('#stocksNewsSection button[data-verdict="CAUTION"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('19_stocks_news_caution.png');

        // Negative
        await page.evaluate(() => {
            const btn = document.querySelector('#stocksNewsSection button[data-verdict="NEGATIVE"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('20_stocks_news_negative.png');

        // =================================================================
        // 7. GLOBAL & MACRO NEWS
        // =================================================================
        console.log("\n--- SECTION 7: GLOBAL NEWS ---");
        await navTo('globalNews');
        await page.waitForTimeout(1000);
        await saveScreenshot(['21_global_macro_news_feed.png', '18_global_news_overview.png']);

        // =================================================================
        // 8. INSTITUTIONAL FLOW
        // =================================================================
        console.log("\n--- SECTION 8: INSTITUTIONAL FLOW ---");
        await navTo('institutionalFlow');
        await page.waitForTimeout(1000);
        await saveScreenshot(['22_institutional_flow_overview.png', '20_institutional_flow_overview.png']);

        // =================================================================
        // 9. ORDER FLOW & CVD ENGINE
        // =================================================================
        console.log("\n--- SECTION 9: ORDER FLOW & CVD ---");
        await navTo('orderFlow');
        await page.waitForTimeout(1000);

        // Closing Window (3:00–3:30)
        await page.evaluate(() => {
            const btn = document.querySelector('[data-cvd-window="closing"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('23_order_flow_closing_window.png');

        // Power Hour Window (2:30–3:30)
        await page.evaluate(() => {
            const btn = document.querySelector('[data-cvd-window="power_hour"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('24_order_flow_power_hour_window.png');

        // Full Session
        await page.evaluate(() => {
            const btn = document.querySelector('[data-cvd-window="session"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot(['25_order_flow_full_session_window.png', '21_order_flow_full_session.png', '21_order_flow_overview.png']);

        // Confirmed Filter
        await page.evaluate(() => {
            const btn = document.querySelector('[data-of-filter="CONFIRMED"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('26_order_flow_confirmed_filter.png');

        // Vetoed Filter
        await page.evaluate(() => {
            const btn = document.querySelector('[data-of-filter="VETOED"]');
            if (btn) btn.click();
        });
        await page.waitForTimeout(800);
        await saveScreenshot('27_order_flow_vetoed_filter.png');

        // =================================================================
        // 10. ACCURACY & PERFORMANCE
        // =================================================================
        console.log("\n--- SECTION 10: ACCURACY & PERFORMANCE ---");
        await navTo('accuracy');
        await page.waitForTimeout(1000);
        await saveScreenshot('28_accuracy_performance_dashboard.png');

        // =================================================================
        // 11. HISTORY & CALIBRATION
        // =================================================================
        console.log("\n--- SECTION 11: HISTORY & CALIBRATION ---");
        await navTo('history');
        await page.waitForTimeout(1000);
        await saveScreenshot('29_history_and_calibration.png');

        // Scroll to calibration matrix & histogram
        await page.evaluate(() => {
            window.scrollTo(0, document.body.scrollHeight / 2);
        });
        await page.waitForTimeout(800);
        await saveScreenshot('30_history_calibration_matrix_and_histogram.png');
        await page.evaluate(() => window.scrollTo(0, 0));

        // =================================================================
        // 12. SYSTEM HEALTH & DIAGNOSTICS
        // =================================================================
        console.log("\n--- SECTION 12: SYSTEM HEALTH ---");
        await navTo('systemHealth');
        await page.waitForTimeout(1000);
        await saveScreenshot('31_system_health_and_diagnostics.png');

        // =================================================================
        // 13. GUIDE & SETTINGS
        // =================================================================
        console.log("\n--- SECTION 13: GUIDE & SETTINGS ---");
        await navTo('guide');
        await page.waitForTimeout(1000);
        await saveScreenshot('32_guide_and_settings.png');

        // =================================================================
        // 14. RULES & METHODOLOGY
        // =================================================================
        console.log("\n--- SECTION 14: RULES & METHODOLOGY ---");
        await navTo('rules');
        await page.waitForTimeout(1000);
        await saveScreenshot('33_rules_and_methodology.png');

        // =================================================================
        // 15. MOBILE RESPONSIVENESS AUDIT VIEWS
        // =================================================================
        console.log("\n--- SECTION 15: MOBILE RESPONSIVE VIEWS ---");
        
        // 428px Indices
        await page.setViewportSize({ width: 428, height: 926 });
        await navTo('indices');
        await page.waitForTimeout(1000);
        await saveScreenshot('09_mobile_428px_indices.png');

        // 428px Option Chain
        await page.evaluate(async () => {
            if (typeof window.openOptionChainModal === 'function') {
                await window.openOptionChainModal('NIFTY');
            }
        });
        await page.waitForTimeout(1200);
        await saveScreenshot('10_mobile_428px_option_chain.png');
        await page.evaluate(() => {
            if (typeof window.closeOptionChainModal === 'function') window.closeOptionChainModal();
        });

        // 390px Indices
        await page.setViewportSize({ width: 390, height: 844 });
        await navTo('indices');
        await page.waitForTimeout(1000);
        await saveScreenshot('09_mobile_390px_indices.png');

        // 390px Option Chain
        await page.evaluate(async () => {
            if (typeof window.openOptionChainModal === 'function') {
                await window.openOptionChainModal('NIFTY');
            }
        });
        await page.waitForTimeout(1200);
        await saveScreenshot('10_mobile_390px_option_chain.png');
        await page.evaluate(() => {
            if (typeof window.closeOptionChainModal === 'function') window.closeOptionChainModal();
        });

        // 375px Indices
        await page.setViewportSize({ width: 375, height: 812 });
        await navTo('indices');
        await page.waitForTimeout(1000);
        await saveScreenshot('09_mobile_375px_indices.png');

        // 375px Option Chain
        await page.evaluate(async () => {
            if (typeof window.openOptionChainModal === 'function') {
                await window.openOptionChainModal('NIFTY');
            }
        });
        await page.waitForTimeout(1200);
        await saveScreenshot('10_mobile_375px_option_chain.png');
        await page.evaluate(() => {
            if (typeof window.closeOptionChainModal === 'function') window.closeOptionChainModal();
        });

        console.log("\n===============================================================");
        console.log("  🎉 ALL SCREENSHOTS SUCCESSFULLY UPDATED AND REPLACED!");
        console.log("===============================================================\n");

    } catch (err) {
        console.error("Error during screenshot capture:", err);
    } finally {
        await browser.close();
    }
})();
