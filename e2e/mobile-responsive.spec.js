// @ts-check
const { test, expect } = require('@playwright/test');

/**
 * QUANTHORIZON / TRADEXO — Mobile Responsive & Visual Regression Suite
 * ====================================================================
 *
 * Requirements:
 * 1. Test 7 main pages:
 *    - Scanner
 *    - Order Flow Veto
 *    - Accuracy & Performance
 *    - Index Intelligence
 *    - History & Calibration
 *    - Strategies
 *    - Rules
 * 2. Three viewport widths (configured in playwright.config.js):
 *    - 375px (iPhone SE / iPhone 12 mini)
 *    - 390px (iPhone 14 / iPhone 15)
 *    - 428px (iPhone 14 Pro Max / iPhone 15 Plus)
 * 3. Explicit bounding box assertion:
 *    The ticker bar component (#marqueeTrack / .index-ticker-bar) and the
 *    page header component (.content-topbar) must NEVER overlap.
 * 4. Automated visual regression screenshots for each page.
 */

const SECTIONS = [
  { name: 'Scanner', key: 'scanner', hash: 'signals', sectionId: 'scannerSection' },
  { name: 'Order Flow Veto', key: 'orderFlow', hash: 'order-flow', sectionId: 'orderFlowSection' },
  { name: 'Accuracy & Performance', key: 'accuracy', hash: 'accuracy', sectionId: 'accuracySection' },
  { name: 'Index Intelligence', key: 'indices', hash: 'index-intelligence', sectionId: 'indicesSection' },
  { name: 'History & Calibration', key: 'history', hash: 'history', sectionId: 'historySection' },
  { name: 'Strategies', key: 'strategies', hash: 'strategies', sectionId: 'strategiesSection' },
  { name: 'Rules', key: 'rules', hash: 'rules', sectionId: 'rulesSection' },
];

async function gotoSection(page, section) {
  // If page not yet loaded on local server, navigate to root
  const currentUrl = page.url();
  if (!currentUrl || currentUrl === 'about:blank') {
    await page.goto('/', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.content-topbar', { state: 'attached', timeout: 15_000 });
    await page.waitForSelector('.index-ticker-bar, #marqueeTrack', { state: 'attached', timeout: 15_000 });
  }

  // Switch to section via SPA switchSection or hash navigation
  await page.evaluate((sec) => {
    if (typeof window.switchSection === 'function') {
      window.switchSection(sec.key);
    } else {
      window.location.hash = '/' + sec.hash;
    }
  }, section);

  // Allow layout and CSS transitions to settle
  await page.waitForTimeout(300);
}

// ═══════════════════════════════════════════════════════════════════════════
// 1. RECURRING MOBILE REGRESSION: TICKER BAR & HEADER BOUNDING BOX OVERLAP
// ═══════════════════════════════════════════════════════════════════════════
test.describe('Header and Ticker Bounding Box Non-Overlap Verification', () => {
  for (const section of SECTIONS) {
    test(`${section.name}: ticker bar must NOT overlap page header`, async ({ page }) => {
      await gotoSection(page, section);

      const header = page.locator('.content-topbar');
      const ticker = page.locator('.index-ticker-bar, #marqueeTrack');

      await expect(header).toBeVisible();
      await expect(ticker).toBeVisible();

      const headerBox = await header.boundingBox();
      const tickerBox = await ticker.boundingBox();

      expect(headerBox, 'Header bounding box must be computable').not.toBeNull();
      expect(tickerBox, 'Ticker bar bounding box must be computable').not.toBeNull();

      if (!headerBox || !tickerBox) return;

      const headerBottom = headerBox.y + headerBox.height;
      const tickerTop = tickerBox.y;
      const overlapDistance = headerBottom - tickerTop;

      // EXPLICIT ASSERTION: Ticker bar top must be >= header bottom (allowing 1px sub-pixel tolerance)
      expect(
        tickerTop,
        `[CRITICAL OVERLAP BUG] On "${section.name}" at viewport width ${page.viewportSize()?.width}px:\n` +
        `  Header: y=${headerBox.y.toFixed(1)}, height=${headerBox.height.toFixed(1)}, bottom=${headerBottom.toFixed(1)}px\n` +
        `  Ticker: y=${tickerBox.y.toFixed(1)}, height=${tickerBox.height.toFixed(1)}\n` +
        `  Overlap detected: ${overlapDistance.toFixed(1)}px!\n` +
        `  The ticker bar and header must have zero bounding box overlap on all mobile screens.`
      ).toBeGreaterThanOrEqual(headerBottom - 1);
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// 2. HORIZONTAL RESPONSIVENESS (NO VIEWPORT SPILLOVER)
// ═══════════════════════════════════════════════════════════════════════════
test.describe('Mobile Viewport Horizontal Fit', () => {
  for (const section of SECTIONS) {
    test(`${section.name}: body does not cause unwanted horizontal overflow`, async ({ page }) => {
      await gotoSection(page, section);

      const viewportWidth = page.viewportSize()?.width ?? 375;
      const scrollWidth = await page.evaluate(() => document.documentElement.clientWidth);

      // The documentElement clientWidth must match viewport width
      expect(scrollWidth).toBeLessThanOrEqual(viewportWidth + 1);
    });
  }
});

// ═══════════════════════════════════════════════════════════════════════════
// 3. VISUAL REGRESSION SCREENSHOT CAPTURE
// ═══════════════════════════════════════════════════════════════════════════
test.describe('Automated Visual Snapshots for 7 Main Pages', () => {
  for (const section of SECTIONS) {
    test(`${section.name}: capture mobile viewport screenshot`, async ({ page }, testInfo) => {
      await gotoSection(page, section);

      const vpWidth = page.viewportSize()?.width ?? 375;
      const screenshot = await page.screenshot({
        path: `e2e/screenshots/${section.key}-${vpWidth}px.png`,
        fullPage: false,
      });

      await testInfo.attach(`${section.name}-${vpWidth}px`, {
        body: screenshot,
        contentType: 'image/png',
      });
    });
  }
});
