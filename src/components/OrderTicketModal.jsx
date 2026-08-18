import React, { useState, useMemo, useEffect } from 'react';

/**
 * Institutional Order Ticket Modal (React + Tailwind CSS)
 * 
 * Features:
 * - Real-time Capital Risk % vs. Fixed Quantity calculation
 * - F&O lot-size snapping (Nifty: 25, BankNifty: 15, Sensex: 10, etc.)
 * - Market slippage & Limit order execution modes
 * - Margin requirement and simulated brokerage/STT breakdown
 */
export default function OrderTicketModal({
  isOpen,
  onClose,
  onConfirmTrade,
  setup = {
    symbol: 'RELIANCE',
    signal: 'BTST (BUY)',
    entry_price: 2500.0,
    target_price_1: 2550.0,
    target_price_2: 2600.0,
    stop_loss: 2460.0
  },
  accountEquity = 1000000.0
}) {
  const [orderType, setOrderType] = useState('MARKET'); // 'MARKET' | 'LIMIT'
  const [sizingMode, setSizingMode] = useState('RISK'); // 'RISK' | 'FIXED'
  const [riskPercent, setRiskPercent] = useState(1.0);
  const [limitPrice, setLimitPrice] = useState(setup.entry_price || 100.0);
  const [quantity, setQuantity] = useState(50);
  const [targetPrice, setTargetPrice] = useState(setup.target_price_1 || (setup.entry_price * 1.02));
  const [stopLoss, setStopLoss] = useState(setup.stop_loss || (setup.entry_price * 0.985));
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Determine Instrument Lot Size
  const lotSize = useMemo(() => {
    const s = String(setup.symbol || '').toUpperCase().trim();
    if (s.includes('BANKNIFTY') || s.includes('BANKEX')) return 15;
    if (s.includes('FINNIFTY') || s.includes('NIFTY')) return 25;
    if (s.includes('SENSEX')) return 10;
    if (s.includes('MIDCPNIFTY')) return 50;
    return 1; // Standard equity stock
  }, [setup.symbol]);

  // Is Bullish / Bearish
  const isBullish = useMemo(() => {
    const sig = String(setup.signal || '').toUpperCase();
    return sig.includes('BUY') || sig.includes('BTST') || sig.includes('CALL');
  }, [setup.signal]);

  // Auto-calculate quantity on Risk % or SL change
  useEffect(() => {
    if (sizingMode === 'RISK') {
      const activePrice = orderType === 'LIMIT' ? Number(limitPrice) : Number(setup.entry_price || 100.0);
      const riskPerShare = Math.max(0.5, Math.abs(activePrice - Number(stopLoss)));
      const riskCapital = (accountEquity * riskPercent) / 100.0;
      let calculatedQty = Math.max(1, Math.floor(riskCapital / riskPerShare));

      if (lotSize > 1) {
        calculatedQty = Math.max(lotSize, Math.round(calculatedQty / lotSize) * lotSize);
      }
      setQuantity(calculatedQty);
    }
  }, [sizingMode, riskPercent, stopLoss, limitPrice, orderType, setup.entry_price, accountEquity, lotSize]);

  // Financial Estimates
  const { tradeValue, riskAmount, riskPctOfAccount, estimatedCharges, totalMarginRequired } = useMemo(() => {
    const activePrice = orderType === 'LIMIT' ? Number(limitPrice) : Number(setup.entry_price || 100.0);
    const qty = Number(quantity) || 1;
    const tVal = activePrice * qty;
    const rAmt = Math.abs(activePrice - Number(stopLoss)) * qty;
    const rPct = accountEquity > 0 ? ((rAmt / accountEquity) * 100).toFixed(2) : '0.00';
    
    // ₹20 Flat Brokerage + 0.1% STT simulation
    const charges = 20.0 + (tVal * 0.001);
    const marginReq = tVal + 20.0;

    return {
      tradeValue: tVal,
      riskAmount: rAmt,
      riskPctOfAccount: rPct,
      estimatedCharges: charges,
      totalMarginRequired: marginReq
    };
  }, [orderType, limitPrice, setup.entry_price, quantity, stopLoss, accountEquity]);

  if (!isOpen) return null;

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      const payload = {
        symbol: setup.symbol,
        signal: setup.signal,
        order_type: isBullish ? 'BUY' : 'SELL',
        execution_mode: orderType,
        entry_price: orderType === 'LIMIT' ? Number(limitPrice) : Number(setup.entry_price),
        quantity: Number(quantity),
        target_price_1: Number(targetPrice),
        target_price_2: Number(setup.target_price_2 || (Number(targetPrice) * 1.02)),
        stop_loss: Number(stopLoss)
      };
      if (onConfirmTrade) {
        await onConfirmTrade(payload);
      }
      onClose();
    } catch (err) {
      console.error('Paper trade submission failed:', err);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-md p-6 shadow-2xl relative text-slate-100 animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <span className={`px-2.5 py-1 text-xs font-black rounded-md ${isBullish ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'}`}>
              {isBullish ? 'BUY (CALL)' : 'SELL (PUT)'}
            </span>
            <h2 className="text-xl font-extrabold tracking-wide">{setup.symbol}</h2>
          </div>
          <button 
            onClick={onClose} 
            className="text-slate-400 hover:text-white transition-colors text-2xl leading-none"
          >
            &times;
          </button>
        </div>

        {/* Live LTP & Account Info */}
        <div className="flex items-center justify-between bg-slate-950/60 border border-slate-800/80 rounded-xl px-4 py-3 my-4">
          <span className="text-xs text-slate-400 font-medium">LIVE LTP:</span>
          <span className={`text-lg font-mono font-black ${isBullish ? 'text-emerald-400' : 'text-rose-400'}`}>
            ₹{Number(setup.entry_price || 100.0).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        {/* Order Type Toggle */}
        <div className="mb-4">
          <label className="text-[11px] font-bold text-slate-400 tracking-wider uppercase block mb-1.5">ORDER TYPE</label>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => setOrderType('MARKET')}
              className={`py-2 px-3 text-xs font-bold rounded-lg transition-all ${orderType === 'MARKET' ? 'bg-yellow-500 text-slate-950 font-black shadow-lg shadow-yellow-500/20' : 'bg-slate-800 hover:bg-slate-700 text-slate-300'}`}
            >
              MARKET (Slippage Sim)
            </button>
            <button
              type="button"
              onClick={() => setOrderType('LIMIT')}
              className={`py-2 px-3 text-xs font-bold rounded-lg transition-all ${orderType === 'LIMIT' ? 'bg-yellow-500 text-slate-950 font-black shadow-lg shadow-yellow-500/20' : 'bg-slate-800 hover:bg-slate-700 text-slate-300'}`}
            >
              LIMIT
            </button>
          </div>
        </div>

        {/* Limit Price Input */}
        {orderType === 'LIMIT' && (
          <div className="mb-4">
            <label className="text-[11px] font-bold text-slate-400 tracking-wider uppercase block mb-1.5">LIMIT PRICE (₹)</label>
            <input
              type="number"
              step="0.05"
              value={limitPrice}
              onChange={(e) => setLimitPrice(parseFloat(e.target.value) || 0)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm font-bold text-white focus:outline-none focus:border-yellow-500"
            />
          </div>
        )}

        {/* Sizing Method & Risk Presets */}
        <div className="mb-4">
          <div className="flex justify-between items-center mb-1.5">
            <label className="text-[11px] font-bold text-slate-400 tracking-wider uppercase">POSITION SIZING</label>
            <span className="text-[11px] font-bold text-yellow-500">Virtual Equity: ₹{accountEquity.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
          </div>
          <div className="grid grid-cols-2 gap-2 mb-2">
            <button
              type="button"
              onClick={() => setSizingMode('RISK')}
              className={`py-1.5 text-xs font-bold rounded-md transition-all ${sizingMode === 'RISK' ? 'bg-yellow-500 text-slate-950' : 'bg-slate-800 text-slate-300'}`}
            >
              RISK % ALLOCATION
            </button>
            <button
              type="button"
              onClick={() => setSizingMode('FIXED')}
              className={`py-1.5 text-xs font-bold rounded-md transition-all ${sizingMode === 'FIXED' ? 'bg-yellow-500 text-slate-950' : 'bg-slate-800 text-slate-300'}`}
            >
              FIXED QUANTITY
            </button>
          </div>

          {sizingMode === 'RISK' && (
            <div className="grid grid-cols-4 gap-1.5 mt-2">
              {[0.5, 1.0, 2.0, 3.0].map((pct) => (
                <button
                  key={pct}
                  type="button"
                  onClick={() => setRiskPercent(pct)}
                  className={`py-1 text-xs font-semibold rounded ${riskPercent === pct ? 'bg-yellow-500 text-slate-950 font-bold' : 'bg-slate-800/80 hover:bg-slate-700 text-slate-300'}`}
                >
                  {pct}%
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Quantity & Lot Size */}
        <div className="mb-4">
          <div className="flex justify-between items-center mb-1.5">
            <label className="text-[11px] font-bold text-slate-400 tracking-wider uppercase">QUANTITY</label>
            <span className="text-[10px] font-extrabold px-2 py-0.5 rounded bg-yellow-500/20 text-yellow-400 border border-yellow-500/30">
              {lotSize > 1 ? `LOT: ${lotSize}` : 'EQUITY (1x)'}
            </span>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setQuantity((prev) => Math.max(lotSize, prev - lotSize))}
              className="px-3 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-lg"
            >
              -
            </button>
            <input
              type="number"
              step={lotSize}
              min={lotSize}
              value={quantity}
              onChange={(e) => setQuantity(Math.max(lotSize, parseInt(e.target.value, 10) || lotSize))}
              className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-center text-sm font-black text-white focus:outline-none focus:border-yellow-500"
            />
            <button
              type="button"
              onClick={() => setQuantity((prev) => prev + lotSize)}
              className="px-3 bg-slate-800 hover:bg-slate-700 text-white font-bold rounded-lg"
            >
              +
            </button>
          </div>
        </div>

        {/* Target & Stop Loss Inputs */}
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className="text-[11px] font-bold text-emerald-400 tracking-wider uppercase block mb-1">TARGET (TP)</label>
            <input
              type="number"
              step="0.05"
              value={targetPrice}
              onChange={(e) => setTargetPrice(parseFloat(e.target.value) || 0)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm font-bold text-emerald-400 focus:outline-none focus:border-emerald-500"
            />
          </div>
          <div>
            <label className="text-[11px] font-bold text-rose-400 tracking-wider uppercase block mb-1">STOP LOSS (SL)</label>
            <input
              type="number"
              step="0.05"
              value={stopLoss}
              onChange={(e) => setStopLoss(parseFloat(e.target.value) || 0)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm font-bold text-rose-400 focus:outline-none focus:border-rose-500"
            />
          </div>
        </div>

        {/* Cost & Risk Breakdown Summary */}
        <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-3.5 mb-5 space-y-1.5 text-xs">
          <div className="flex justify-between text-slate-400">
            <span>Trade Value:</span>
            <span className="font-semibold text-white">₹{tradeValue.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Risk at Stop Loss:</span>
            <span className="font-semibold text-rose-400">₹{riskAmount.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({riskPctOfAccount}%)</span>
          </div>
          <div className="flex justify-between text-slate-400">
            <span>Simulated Costs (₹20 + 0.1% STT):</span>
            <span className="font-semibold text-yellow-500">₹{estimatedCharges.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-white font-bold pt-2 border-t border-slate-800/80">
            <span>Total Margin Required:</span>
            <span className="text-yellow-400 font-mono text-sm">₹{totalMarginRequired.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>
        </div>

        {/* Execution Button */}
        <button
          type="button"
          disabled={isSubmitting}
          onClick={handleSubmit}
          className="w-full py-3.5 bg-yellow-500 hover:bg-yellow-400 disabled:opacity-50 text-slate-950 font-black text-sm tracking-wider uppercase rounded-xl transition-all shadow-lg shadow-yellow-500/25 active:scale-[0.98]"
        >
          {isSubmitting ? 'ROUTING ORDER...' : 'CONFIRM PAPER TRADE'}
        </button>

      </div>
    </div>
  );
}
