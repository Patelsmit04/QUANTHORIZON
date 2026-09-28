// @ts-check
const { defineConfig, devices } = require('@playwright/test');

/**
 * QUANTHORIZON / TRADEXO — Playwright Responsive Regression Test Config
 *
 * Tests run against a live local dev server (python app.py on port 8000).
 * Three mobile viewports (375px / 390px / 428px) are exercised against every
 * section of the SPA to catch the recurring header/ticker-bar overlap bug and
 * any other layout regressions automatically before deploy.
 */
module.exports = defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [['list']],
  timeout: 30_000,
  use: {
    baseURL: process.env.BASE_URL || 'http://127.0.0.1:8000',
    // Capture screenshot on failure for debugging
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [
    // ── iPhone SE / iPhone 12 mini class (375px) ──
    {
      name: 'mobile-375',
      use: {
        viewport: { width: 375, height: 812 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      },
    },
    // ── iPhone 14 / 15 class (390px) ──
    {
      name: 'mobile-390',
      use: {
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      },
    },
    // ── iPhone 14 Pro Max / 15 Plus class (428px) ──
    {
      name: 'mobile-428',
      use: {
        viewport: { width: 428, height: 926 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
        userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
      },
    },
  ],
});
