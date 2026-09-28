import React from "react";
import { cn } from "../../lib/utils.js";

/**
 * shadcn/ui Switch component (Radix UI-grade accessible toggle)
 *
 * Features:
 * - WAI-ARIA role="switch" and aria-checked attribute
 * - Keyboard navigation (Spacebar / Enter support)
 * - 44px minimum touch target compliance for mobile audits
 * - Accessible focus-visible rings (amber accent)
 * - Smooth CSS spring transitions
 */
export function Switch({
  checked = false,
  onCheckedChange,
  disabled = false,
  className,
  id,
  name,
  "aria-label": ariaLabel,
  ...props
}) {
  const handleClick = () => {
    if (disabled) return;
    if (onCheckedChange) {
      onCheckedChange(!checked);
    }
  };

  const handleKeyDown = (e) => {
    if (disabled) return;
    if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      handleClick();
    }
  };

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      id={id}
      name={name}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        "peer inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 min-h-[44px] min-w-[44px] p-1 box-content touch-manipulation",
        checked
          ? "bg-amber-500 dark:bg-amber-500"
          : "bg-slate-300 dark:bg-slate-700",
        className
      )}
      {...props}
    >
      <span
        className={cn(
          "pointer-events-none block h-5 w-5 rounded-full bg-white shadow-md ring-0 transition-transform duration-200 ease-in-out",
          checked ? "translate-x-5" : "translate-x-0"
        )}
      />
    </button>
  );
}
