# TRACE — Design System & Visual Guidelines
## Professional Swiss-Minimalist Financial Integrity Dashboard

Reference: [impeccable.style](https://impeccable.style/) | CASCADE '26

---

### 1. Design Philosophy

The TRACE dashboard is designed as an institutional-grade financial audit terminal. It prioritizes **clarity, truthfulness, precision, and scannability** over decorative flair.

#### Core Tenets
1. **No "AI Slop" Tells**:
   - **No decorative kicker soup**: Avoid adding redundant uppercase micro-labels (`PROJECT IDENTITY`, `CRYPTOGRAPHIC TRACE`) above every title.
   - **No badge bloat**: Badges are reserved for meaningful state transitions (e.g., `VERIFIED`, `PROJECT FROZEN`, `BLOCKED`). They are not used as decorative tags on static labels.
   - **No artificial gradients / glow vignettes**: Flat bone-white background with subtle structural dividers. No cyan/blue blur borders or glassmorphism.
   - **No nested card containers**: Prefer clean border dividers, tabular columns, and whitespace over cards inside cards.
2. **Tabular Numerals & High Scannability**:
   - All financial figures (ETH, USD, cents, wei) and cryptographic identifiers (hashes, nullifiers, addresses) use tabular monospace styling (`font-variant-numeric: tabular-nums`).
3. **Truthful Financial & Security Representation**:
   - Every metric displayed is sourced from backend state.
   - Discrepancies are explicitly highlighted; zero-discrepancy states are never fabricated.
   - Unspent fiat is reported as residual balance, not spent funds.

---

### 2. Design Tokens

#### Color Palette
```css
:root {
  /* Surfaces & Canvas */
  --bg-page: #F8F9FA;           /* Crisp bone-white neutral canvas */
  --bg-surface: #FFFFFF;        /* Pure white panel background */
  --bg-subtle: #F1F5F9;         /* Neutral slate background for headers / data strips */
  --bg-canvas-inset: #F8FAFC;   /* Inset well background for code / log viewers */

  /* Text & Typography */
  --text-primary: #0F172A;      /* Deep slate 900 for primary text */
  --text-secondary: #334155;    /* Slate 700 for subtitles and labels */
  --text-muted: #64748B;        /* Slate 500 for metadata and secondary context */
  --text-inverse: #FFFFFF;      /* White text on solid dark buttons */

  /* Structural Borders */
  --border-subtle: #E2E8F0;     /* Default 1px subtle divider */
  --border-strong: #CBD5E1;     /* Emphasized border on active/hovered elements */
  --border-dark: #94A3B8;       /* High-contrast border for interactive nodes */

  /* Semantic State Tokens */
  /* Verified / Success */
  --color-success: #059669;
  --color-success-bg: #ECFDF5;
  --color-success-border: #A7F3D0;

  /* Rejection / Critical Security Failure */
  --color-danger: #DC2626;
  --color-danger-bg: #FEF2F2;
  --color-danger-border: #FECACA;

  /* Warning / Gate Lock */
  --color-warning: #B45309;
  --color-warning-bg: #FFFBEB;
  --color-warning-border: #FDE68A;

  /* Informational / Simulated */
  --color-info: #2563EB;
  --color-info-bg: #EFF6FF;
  --color-info-border: #BFDBFE;

  /* Typography Stacks */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, "Liberation Mono", monospace;

  /* Border Radii */
  --radius-xs: 2px;
  --radius-sm: 4px;
  --radius-md: 6px;

  /* Focus Indicator */
  --focus-ring: 2px solid #0F172A;
}
```

---

### 3. Component Hierarchy & Layout Guidelines

#### Header & Action Bar
- Compact height (56px).
- Institutional wordmark: `TRACE` (black, heavy sans) with slash separator and subtitle `THE BLACK HOLE LEDGER`.
- Environment indicators: subtle dot indicator for `API CONNECTED` and discreet badge for `LOCAL SIMULATION`.
- Operational Actions: Primary action `REFRESH` and secondary action `RESET DEMO` cleanly accessible in the header area.

#### Metric Cards
- 4-column desktop layout collapsing to 2-column on tablet and 1-column on mobile.
- Format:
  - Metric label in crisp, small muted uppercase.
  - Large tabular numeral (`28px`, bold, tabular-nums).
  - Explicit currency unit (`ETH` or `$ USD`).
  - Clear explanatory subtext without unnecessary pill badges.

#### Tranche Disbursement Gate
- Clear linear layout: Current progress, release requirements, deficit calculations.
- Clean status pill: `TRANCHE 1 READY`, `TRANCHE N UNLOCKED`, `LOCKED (DEFICIT)`, or `BLOCKED (FROZEN)`.
- Backend evaluation outcome box with direct status code and explanatory text.

#### Fund Flow Graph
- Horizontal chain sequence: `DONATION` $\to$ `ALLOCATION` $\to$ `SWAP` $\to$ `BRIDGE` $\to$ `OFFRAMP` $\to$ `VENDOR PAYMENT`.
- Distinct marker between Real Settlement (Genesis) vs Simulated Engine Hops.
- Clear connectors with directional arrows.
- Clickable node inspection drawer opening cleanly beneath the canvas.

#### Claims & Evidence Table
- High-density table layout with hover row highlights.
- Clear status indicators: `VERIFIED` (emerald) vs `REJECTED` (crimson).
- Evidence commitment hash truncated with full hash reveal on click.
- Monospace nullifier display.

#### Scenario Console
- Logical grouping:
  1. **Benign Demonstrations** (Valid claim with/without evidence).
  2. **Security Defenses** (Tampered amounts, forged signatures, cross-report duplicate invoices, unauthorized categories).
- High visual distinction without looking like a toy: clean buttons with explicit hover and active states.
- Dedicated frozen state alert providing immediate 1-click reset access.

#### Audit Log & Timeline
- Real-time statistics counters in a single horizontal strip.
- High-density ledger table with timestamp, severity level, event type, reason code, and JSON payload viewer.

---

### 4. Responsive Breakpoints

| Breakpoint | Target Devices | Layout Behavior |
| :--- | :--- | :--- |
| **$\ge$ 1200px** | Desktop monitors | Full 4-column metric grid, 3-column scenarios, full table |
| **768px – 1024px** | Tablets / small laptops | 2-column metrics, horizontal scrolling on graph and tables |
| **< 768px** | Mobile devices | 1-column metrics, stacked header, collapsed scenario cards |
| **375px** | Small phones | Zero horizontal page overflow; self-contained scrolling tables |
