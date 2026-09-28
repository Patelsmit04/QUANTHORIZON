import React, { useState, useMemo } from "react";
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
 * Options Demo Trading Modal (Migrated to shadcn/ui Dialog)
 *
 * Provides:
 * - Direct F&O contract execution in virtual paper trading environment
 * - Automatic strike calculation and CE/PE selection
 * - Lot size snapping & margin requirement estimation
 * - Full Radix-grade accessibility (focus trap, ESC close, ARIA attributes)
 * - Minimum 44px touch targets on mobile
 */
export default function OptionsDemoTradeModal({
  isOpen,
  onClose,
  onExecuteTrade,
  initialData = {
    symbol: "NIFTY",
    underlyingLtp: 24500.0,
    leg: "CE",
    strike: 24500,
    lotSize: 25,
    virtualCash: 1000000.0,
  },
}) {
  const [symbol, setSymbol] = useState(initialData.symbol || "NIFTY");
  const [leg, setLeg] = useState(initialData.leg || "CE"); // 'CE' | 'PE'
  const [strike, setStrike] = useState(
    initialData.strike || Math.round((initialData.underlyingLtp || 24500) / 50) * 50
  );
  const [lots, setLots] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const lotSize = useMemo(() => {
    const s = symbol.toUpperCase().trim();
    if (s.includes("BANKNIFTY")) return 15;
    if (s.includes("FINNIFTY") || s.includes("NIFTY")) return 25;
    if (s.includes("SENSEX")) return 10;
    return initialData.lotSize || 25;
  }, [symbol, initialData.lotSize]);

  // Estimated premium model
  const estimatedPremium = useMemo(() => {
    const spot = initialData.underlyingLtp || 24500.0;
    const diff = leg === "CE" ? spot - strike : strike - spot;
    const intrinsic = Math.max(0, diff);
    const timeValue = Math.max(15.0, spot * 0.008);
    return Math.max(1.5, Number((intrinsic + timeValue).toFixed(2)));
  }, [strike, leg, initialData.underlyingLtp]);

  const totalQuantity = lots * lotSize;
  const totalCost = Number((estimatedPremium * totalQuantity).toFixed(2));
  const virtualCash = initialData.virtualCash || 1000000.0;
  const hasSufficientMargin = virtualCash >= totalCost;

  const handleExecute = async () => {
    if (!hasSufficientMargin) return;
    setIsSubmitting(true);
    try {
      const payload = {
        symbol: symbol.toUpperCase().trim(),
        instrument_type: "OPTION",
        leg: leg,
        strike: strike,
        lots: lots,
        lot_size: lotSize,
        quantity: totalQuantity,
        premium: estimatedPremium,
        total_margin: totalCost,
      };
      if (onExecuteTrade) {
        await onExecuteTrade(payload);
      }
      onClose();
    } catch (err) {
      console.error("Options demo trade execution failed:", err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent onClose={onClose} className="max-w-md p-6">
        <DialogHeader className="pb-3 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-2">
            <span
              className={`px-2.5 py-1 text-xs font-black rounded-md ${
                leg === "CE"
                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800"
                  : "bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-950/40 dark:text-rose-400 dark:border-rose-800"
              }`}
            >
              {leg === "CE" ? "CALL (CE)" : "PUT (PE)"}
            </span>
            <DialogTitle className="text-xl font-extrabold tracking-wide">
              {symbol} Options Trade
            </DialogTitle>
          </div>
          <DialogDescription>
            Virtual paper trading for live Index & Stock Options.
          </DialogDescription>
        </DialogHeader>

        {/* Spot and Option Leg Selector */}
        <div className="space-y-4 py-3">
          <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl px-4 py-3">
            <span className="text-xs text-slate-500 dark:text-slate-400 font-bold uppercase">
              SPOT PRICE:
            </span>
            <span className="text-base font-mono font-black text-slate-900 dark:text-slate-100">
              ₹
              {Number(initialData.underlyingLtp || 24500).toLocaleString("en-IN", {
                minimumFractionDigits: 2,
              })}
            </span>
          </div>

          {/* CE vs PE Toggle */}
          <div>
            <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300 tracking-wider uppercase block mb-1.5">
              OPTION TYPE
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setLeg("CE")}
                className={`min-h-[44px] py-2 px-3 text-xs font-bold rounded-xl transition-all ${
                  leg === "CE"
                    ? "bg-emerald-600 text-white font-black shadow-sm"
                    : "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700"
                }`}
              >
                CALL OPTION (CE)
              </button>
              <button
                type="button"
                onClick={() => setLeg("PE")}
                className={`min-h-[44px] py-2 px-3 text-xs font-bold rounded-xl transition-all ${
                  leg === "PE"
                    ? "bg-rose-600 text-white font-black shadow-sm"
                    : "bg-slate-100 hover:bg-slate-200 text-slate-700 border border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700"
                }`}
              >
                PUT OPTION (PE)
              </button>
            </div>
          </div>

          {/* Strike Price */}
          <div>
            <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300 tracking-wider uppercase block mb-1.5">
              STRIKE PRICE (₹)
            </label>
            <input
              type="number"
              step="50"
              value={strike}
              onChange={(e) => setStrike(parseFloat(e.target.value) || 0)}
              className="w-full h-11 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl px-3.5 text-sm font-black text-slate-900 dark:text-slate-100 focus:outline-none focus:border-amber-500"
            />
          </div>

          {/* Lots & Qty */}
          <div>
            <div className="flex justify-between items-center mb-1.5">
              <label className="text-[11px] font-bold text-slate-700 dark:text-slate-300 tracking-wider uppercase">
                LOTS (x{lotSize} QTY)
              </label>
              <span className="text-[11px] font-bold text-amber-600 dark:text-amber-400">
                Total Qty: {totalQuantity}
              </span>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setLots((prev) => Math.max(1, prev - 1))}
                className="min-h-[44px] min-w-[44px] px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-black rounded-xl border border-slate-300 dark:border-slate-700 transition-colors"
              >
                -
              </button>
              <input
                type="number"
                min="1"
                value={lots}
                onChange={(e) => setLots(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="flex-1 h-11 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700 rounded-xl px-3 text-center text-sm font-black text-slate-900 dark:text-slate-100 focus:outline-none focus:border-amber-500"
              />
              <button
                type="button"
                onClick={() => setLots((prev) => prev + 1)}
                className="min-h-[44px] min-w-[44px] px-3 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 font-black rounded-xl border border-slate-300 dark:border-slate-700 transition-colors"
              >
                +
              </button>
            </div>
          </div>

          {/* Premium & Margin Summary */}
          <div className="bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 rounded-xl p-3.5 space-y-2 text-xs">
            <div className="flex justify-between text-slate-600 dark:text-slate-400">
              <span>Estimated Premium:</span>
              <strong className="font-mono text-slate-900 dark:text-slate-100">
                ₹{estimatedPremium.toFixed(2)}
              </strong>
            </div>
            <div className="flex justify-between text-slate-600 dark:text-slate-400">
              <span>Virtual Cash Available:</span>
              <strong className="font-mono text-slate-900 dark:text-slate-100">
                ₹{virtualCash.toLocaleString("en-IN", { maximumFractionDigits: 0 })}
              </strong>
            </div>
            <div className="flex justify-between text-slate-900 dark:text-slate-100 font-bold pt-2 border-t border-slate-200 dark:border-slate-700">
              <span>Total Margin Required:</span>
              <strong className="text-amber-600 dark:text-amber-400 font-mono text-sm">
                ₹{totalCost.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
              </strong>
            </div>
            {!hasSufficientMargin && (
              <p className="text-[11px] font-bold text-rose-600 dark:text-rose-400 pt-1">
                ⚠️ Insufficient virtual margin for this order.
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            disabled={isSubmitting || !hasSufficientMargin}
            onClick={handleExecute}
            variant={leg === "CE" ? "primary" : "destructive"}
            className="w-full h-12 text-sm tracking-wider uppercase font-black"
          >
            {isSubmitting
              ? "Routing Trade..."
              : `Execute ${leg === "CE" ? "Call (CE)" : "Put (PE)"} Trade`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
