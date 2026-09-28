import React, { createContext, useContext, useEffect, useRef } from "react";
import { cn } from "../../lib/utils.js";

const DialogContext = createContext({
  open: false,
  onOpenChange: () => {},
});

export function Dialog({ open = false, onOpenChange = () => {}, children }) {
  return (
    <DialogContext.Provider value={{ open, onOpenChange }}>
      {children}
    </DialogContext.Provider>
  );
}

export function DialogTrigger({ asChild = false, children, ...props }) {
  const { onOpenChange } = useContext(DialogContext);
  const handleClick = (e) => {
    if (props.onClick) props.onClick(e);
    onOpenChange(true);
  };

  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children, {
      ...props,
      onClick: handleClick,
    });
  }

  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}

export function DialogPortal({ children }) {
  return <>{children}</>;
}

export function DialogOverlay({ className, ...props }) {
  return (
    <div
      className={cn(
        "fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-sm transition-opacity duration-200 animate-in fade-in-0",
        className
      )}
      aria-hidden="true"
      {...props}
    />
  );
}

export function DialogContent({ className, children, onClose, ...props }) {
  const { open, onOpenChange } = useContext(DialogContext);
  const contentRef = useRef(null);

  const handleClose = () => {
    if (onClose) onClose();
    onOpenChange(false);
  };

  // Keyboard accessibility: Close on ESC key
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        handleClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [open]);

  // Accessibility: prevent body scroll while dialog is open
  useEffect(() => {
    if (open) {
      const originalOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = originalOverflow;
      };
    }
  }, [open]);

  if (!open) return null;

  return (
    <DialogPortal>
      <DialogOverlay onClick={handleClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
        <div
          ref={contentRef}
          role="dialog"
          aria-modal="true"
          onClick={(e) => e.stopPropagation()}
          className={cn(
            "relative w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl border border-slate-200 text-slate-900 transition-all duration-200 animate-in fade-in-0 zoom-in-95 focus:outline-none dark:bg-slate-900 dark:border-slate-800 dark:text-slate-100",
            className
          )}
          {...props}
        >
          {children}
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close dialog"
            className="absolute right-4 top-4 rounded-lg p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 dark:hover:bg-slate-800 dark:hover:text-slate-200 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 min-h-[44px] min-w-[44px] flex items-center justify-center"
          >
            <span className="text-xl font-semibold leading-none">&times;</span>
          </button>
        </div>
      </div>
    </DialogPortal>
  );
}

export function DialogHeader({ className, ...props }) {
  return (
    <div
      className={cn("flex flex-col space-y-1.5 text-left pb-4 border-b border-slate-100 dark:border-slate-800", className)}
      {...props}
    />
  );
}

export function DialogFooter({ className, ...props }) {
  return (
    <div
      className={cn(
        "flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 pt-4 border-t border-slate-100 dark:border-slate-800",
        className
      )}
      {...props}
    />
  );
}

export function DialogTitle({ className, ...props }) {
  return (
    <h2
      className={cn("text-lg font-bold tracking-tight text-slate-900 dark:text-slate-100", className)}
      {...props}
    />
  );
}

export function DialogDescription({ className, ...props }) {
  return (
    <p
      className={cn("text-xs text-slate-500 dark:text-slate-400", className)}
      {...props}
    />
  );
}

export function DialogClose({ asChild = false, children, ...props }) {
  const { onOpenChange } = useContext(DialogContext);
  const handleClick = (e) => {
    if (props.onClick) props.onClick(e);
    onOpenChange(false);
  };

  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children, {
      ...props,
      onClick: handleClick,
    });
  }

  return (
    <button type="button" onClick={handleClick} {...props}>
      {children}
    </button>
  );
}
