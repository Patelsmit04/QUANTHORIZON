import React from "react";
import { cn } from "../../lib/utils.js";

export function Button({
  className,
  variant = "default",
  size = "default",
  type = "button",
  disabled = false,
  children,
  ...props
}) {
  const baseStyles =
    "inline-flex items-center justify-center rounded-xl font-bold transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500 disabled:pointer-events-none disabled:opacity-50 select-none active:scale-[0.98]";

  const variants = {
    default:
      "bg-amber-500 hover:bg-amber-600 text-slate-950 shadow-md shadow-amber-500/20",
    primary:
      "bg-emerald-600 hover:bg-emerald-700 text-white shadow-md shadow-emerald-600/20",
    destructive:
      "bg-rose-600 hover:bg-rose-700 text-white shadow-md shadow-rose-600/20",
    outline:
      "border border-slate-200 bg-transparent hover:bg-slate-100 text-slate-900 dark:border-slate-800 dark:hover:bg-slate-800 dark:text-slate-100",
    secondary:
      "bg-slate-100 hover:bg-slate-200 text-slate-900 dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-100",
    ghost:
      "hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-300",
    link: "text-amber-500 underline-offset-4 hover:underline",
  };

  const sizes = {
    default: "h-11 px-5 py-2 text-sm min-h-[44px]",
    sm: "h-9 px-3.5 text-xs min-h-[36px]",
    lg: "h-12 px-8 text-base min-h-[48px]",
    icon: "h-11 w-11 min-h-[44px] min-w-[44px] p-0",
  };

  return (
    <button
      type={type}
      disabled={disabled}
      className={cn(baseStyles, variants[variant], sizes[size], className)}
      {...props}
    >
      {children}
    </button>
  );
}
