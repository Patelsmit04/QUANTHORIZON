import React from "react";
import { Switch } from "./ui/switch.jsx";

/**
 * Scope A/B Strategy Toggles Component (Migrated to shadcn/ui Switch)
 *
 * Provides:
 * - Scope A: Stocks (Intraday / Scalping)
 * - Scope B: Index Options (Nifty / BankNifty / Sensex)
 * - Consistent spacing, focus rings, and touch-target compliance (>= 44px)
 */
export default function ScopeStrategyToggles({
  strategyId,
  stocksEnabled = true,
  indicesEnabled = true,
  onToggleStocks,
  onToggleIndices,
  disabled = false,
}) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 p-3.5 space-y-3">
      {/* Scope A Toggle */}
      <div className="flex items-center justify-between gap-3 min-h-[44px]">
        <div className="flex items-center gap-2">
          <span className="text-cyan-500 font-bold">📈</span>
          <div>
            <span className="text-xs font-bold text-slate-900 dark:text-slate-100 block">
              Scope A: Stocks (Intraday / Scalping)
            </span>
            <span className="text-[10px] text-slate-500 dark:text-slate-400">
              Live scanning on high-momentum F&amp;O stocks
            </span>
          </div>
        </div>
        <Switch
          id={`scope-stocks-${strategyId}`}
          aria-label={`Toggle Scope A Stocks for strategy ${strategyId}`}
          checked={stocksEnabled}
          disabled={disabled}
          onCheckedChange={onToggleStocks}
        />
      </div>

      <div className="h-[1px] bg-slate-200 dark:bg-slate-800" />

      {/* Scope B Toggle */}
      <div className="flex items-center justify-between gap-3 min-h-[44px]">
        <div className="flex items-center gap-2">
          <span className="text-amber-500 font-bold">⚡</span>
          <div>
            <span className="text-xs font-bold text-slate-900 dark:text-slate-100 block">
              Scope B: Index Options
            </span>
            <span className="text-[10px] text-slate-500 dark:text-slate-400">
              Scans NIFTY, BANKNIFTY &amp; SENSEX option chains
            </span>
          </div>
        </div>
        <Switch
          id={`scope-indices-${strategyId}`}
          aria-label={`Toggle Scope B Indices for strategy ${strategyId}`}
          checked={indicesEnabled}
          disabled={disabled}
          onCheckedChange={onToggleIndices}
        />
      </div>
    </div>
  );
}
