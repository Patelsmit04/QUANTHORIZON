# Options Terminal Page Overrides

> **PROJECT:** Tradexo
> **Page:** Live Options Execution Panel & Options Terminal
> **Source of Truth:** Overrides `design-system/tradexo/MASTER.md` for options execution contexts.

---

## 1. Surface & Background Tokens

| Token | Value | Role |
|---|---|---|
| `--obsidian-bg` | `#09090b` | Base modal & panel background |
| `--obsidian-surface` | `#121216` | Elevated cards, input fills, dropdowns |
| `--obsidian-elevated` | `#18181b` | Hover states, pill badges, active steppers |
| `--obsidian-border` | `#27272a` | Clean perimeter borders & card dividers |
| `--obsidian-border-subtle` | `rgba(255, 255, 255, 0.08)` | Subtle inner card dividers |
| `--obsidian-text-primary` | `#f4f4f5` | High-contrast headers, values, prices |
| `--obsidian-text-muted` | `#71717a` | Secondary labels, timestamps, lot hints |

---

## 2. Semantic States (Success vs. Danger)

| State | Role | Hex Token | Ambient Surface / Glow |
|---|---|---|---|
| **CALL (CE) / Bullish / Success** | Call leg, profit indicators, target | `#22C55E` (`--color-accent`) | `rgba(34, 197, 94, 0.12)`, glow `0 0 16px rgba(34, 197, 94, 0.25)` |
| **PUT (PE) / Bearish / Danger** | Put leg, stop-loss, margin warning | `#EF4444` (`--color-destructive`) | `rgba(239, 68, 68, 0.12)`, glow `0 0 16px rgba(239, 68, 68, 0.25)` |
| **ATM / Strike / Neutral** | At-the-money strike, warning badge | `#F59E0B` (`--color-warning`) | `rgba(245, 158, 11, 0.15)`, border `rgba(245, 158, 11, 0.35)` |

---

## 3. Typography Rules

- **Font Family for Numeric Feeds:** `font-family: 'Fira Code', 'Roboto Mono', monospace;`
- **Tabular Alignment:** `font-variant-numeric: tabular-nums;`
- **Kerning:** `letter-spacing: -0.02em;`
- **Rule:** ALL prices (underlying LTP, premium LTP), strikes, lot sizes, unit quantities, cash balances, and estimated margin MUST use tabular numbers to eliminate layout shift during live 1-second price ticks.

---

## 4. Iconography Standards

- **Icon Set:** Lucide Icons (rendered as scalable SVG or `data-lucide` attributes).
- **Prohibited:** No emojis (⚡, 📈, 📉, ⚠️) as structural icons.
- **Key Icon Mappings:**
  - Call (CE): `trending-up`
  - Put (PE): `trending-down`
  - Order Execution: `zap`
  - Risk / Margin Alert: `shield-alert`
  - Account / Capital: `wallet`
  - Lots & Contracts: `layers`
  - Close: `x`
  - Steppers: `plus`, `minus`
  - Loading / Pending: `refresh-cw` (with continuous 360° spin)

---

## 5. Component Specifications

### 5.1 Modal Overlay & Card
- Overlay: `background: rgba(0, 0, 0, 0.75); backdrop-filter: blur(12px);`
- Card: `background: #09090b; border: 1px solid #27272a; border-radius: 16px; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.85);`

### 5.2 Leg Toggle Selector (Segmented Pill)
- Container: Grid 1fr 1fr, background `#121216`, padding `4px`, border `1px solid #27272a`, border-radius `10px`.
- Button: `cursor: pointer; font-weight: 700; transition: all 180ms ease;`
- CE Active: `background: rgba(34, 197, 94, 0.15); color: #22c55e; border: 1px solid #22c55e; box-shadow: 0 0 12px rgba(34, 197, 94, 0.2);`
- PE Active: `background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid #ef4444; box-shadow: 0 0 12px rgba(239, 68, 68, 0.2);`

### 5.3 Execution CTA Button
- Full width, min-height `48px`, font-size `14px`, font-weight `800`, letter-spacing `0.5px`, border-radius `10px`.
- Adaptive to Active Leg:
  - CE Active: `background: #22c55e; color: #09090b; box-shadow: 0 0 20px rgba(34, 197, 94, 0.35);`
  - PE Active: `background: #ef4444; color: #ffffff; box-shadow: 0 0 20px rgba(239, 68, 68, 0.35);`
  - Disabled State: `opacity: 0.4; cursor: not-allowed; filter: grayscale(0.5);`
