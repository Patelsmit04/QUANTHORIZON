import React from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "./ui/dialog.jsx";
import { Button } from "./ui/button.jsx";

/**
 * Win Rate & Score Tracker Modal (Migrated to shadcn/ui Dialog)
 *
 * Provides:
 * - Institutional performance metrics (Win Rate, Profit Factor, Accuracy, Expectancy)
 * - Out-of-sample walk-forward validation telemetry
 * - Strategy tier breakdown (Tier 1 vs Tier 2)
 * - Radix-grade accessible focus management, ESC key close, and backdrop blur
 * - Minimum 44px touch targets on mobile
 */
export default function WinRateModal({
  isOpen,
  onClose,
  metrics = {
    winRate: 87.5,
    accuracy: 92.5,
    totalTrades: 124,
    avgGap: 2.8,
    profitFactor: 2.45,
    maxDrawdown: 4.2,
    sharpeRatio: 2.15,
    tier1Trades: 86,
    tier1WinRate: 91.2,
    tier2Trades: 38,
    tier2WinRate: 79.0,
  },
}) {
  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent onClose={onClose} className="max-w-xl max-h-[90vh] overflow-y-auto p-6">
        <DialogHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <span className="text-xl">📊</span>
            <DialogTitle className="text-xl font-extrabold tracking-wide">
              Win Rate &amp; Strategy Telemetry
            </DialogTitle>
          </div>
          <DialogDescription>
            Out-of-sample verified quantitative trade analytics and pillar performance.
          </DialogDescription>
        </DialogHeader>

        <div className="py-4 space-y-4">
          {/* Key Metric Highlights Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-3 text-center">
              <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block">
                WIN RATE
              </span>
              <span className="text-xl font-mono font-black text-amber-500 dark:text-amber-400">
                {metrics.winRate}%
              </span>
            </div>
            <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-3 text-center">
              <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block">
                ACCURACY
              </span>
              <span className="text-xl font-mono font-black text-emerald-600 dark:text-emerald-400">
                {metrics.accuracy}%
              </span>
            </div>
            <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-3 text-center">
              <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block">
                TOTAL TRADES
              </span>
              <span className="text-xl font-mono font-black text-slate-900 dark:text-slate-100">
                {metrics.totalTrades}
              </span>
            </div>
            <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-3 text-center">
              <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block">
                AVG GAP
              </span>
              <span className="text-xl font-mono font-black text-cyan-600 dark:text-cyan-400">
                +{metrics.avgGap}%
              </span>
            </div>
          </div>

          {/* Quantitative Risk Profile */}
          <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-4 space-y-2">
            <h4 className="text-xs font-extrabold tracking-wider uppercase text-slate-700 dark:text-slate-300">
              STRATEGY RISK RATIOS (OUT-OF-SAMPLE)
            </h4>
            <div className="grid grid-cols-3 gap-2 pt-1 text-center">
              <div>
                <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block font-semibold">
                  Profit Factor
                </span>
                <strong className="text-sm font-mono text-emerald-600 dark:text-emerald-400">
                  {metrics.profitFactor}x
                </strong>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block font-semibold">
                  Max Drawdown
                </span>
                <strong className="text-sm font-mono text-rose-600 dark:text-rose-400">
                  -{metrics.maxDrawdown}%
                </strong>
              </div>
              <div>
                <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase block font-semibold">
                  Sharpe Ratio
                </span>
                <strong className="text-sm font-mono text-amber-500 dark:text-amber-400">
                  {metrics.sharpeRatio}
                </strong>
              </div>
            </div>
          </div>

          {/* Conviction Tier Breakdown */}
          <div className="border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden text-xs">
            <div className="bg-slate-100 dark:bg-slate-800 p-2.5 font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
              Conviction Tier Performance
            </div>
            <div className="p-3 space-y-2 bg-white dark:bg-slate-900">
              <div className="flex justify-between items-center">
                <span className="font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-amber-500"></span> Tier 1 (Score ≥ 85)
                </span>
                <span className="font-mono font-bold text-slate-900 dark:text-slate-100">
                  {metrics.tier1Trades} trades • <span className="text-emerald-600 dark:text-emerald-400">{metrics.tier1WinRate}% WR</span>
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span className="font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-slate-400"></span> Tier 2 (Score 70-84)
                </span>
                <span className="font-mono font-bold text-slate-900 dark:text-slate-100">
                  {metrics.tier2Trades} trades • <span className="text-amber-500">{metrics.tier2WinRate}% WR</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button type="button" onClick={onClose} className="w-full sm:w-auto min-h-[44px]">
            Close Telemetry
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
