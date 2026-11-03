import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { PanelRightOpen, X } from "lucide-react";

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export interface ResponsiveDrawerProps {
  children: ReactNode;
  title: string;
  triggerLabel: string;
  side?: "left" | "right";
  triggerIcon?: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  footer?: ReactNode;
}

export function ResponsiveDrawer({
  children,
  title,
  triggerLabel,
  side = "right",
  triggerIcon,
  open: controlledOpen,
  onOpenChange,
  footer,
}: ResponsiveDrawerProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const open = controlledOpen ?? uncontrolledOpen;
  const titleId = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const backdropPress = useRef<{ pointerId:number; x:number; y:number; moved:boolean; released:boolean } | null>(null);

  useEffect(() => {
    if (!open) {
      backdropPress.current = null;
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogRef.current?.querySelector<HTMLElement>(focusableSelector)?.focus({ preventScroll: true });

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  function setOpen(nextOpen: boolean) {
    if (controlledOpen === undefined) {
      setUncontrolledOpen(nextOpen);
    }
    onOpenChange?.(nextOpen);
  }

  function closeDrawer() {
    setOpen(false);
    triggerRef.current?.focus({ preventScroll: true });
  }

  useEffect(() => {
    if (!open) return;
    // A wizard step may unmount its focused button. Escape must still close
    // the dialog when the browser has temporarily returned focus to body.
    function handleEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        if (controlledOpen === undefined) setUncontrolledOpen(false);
        onOpenChange?.(false);
        triggerRef.current?.focus({ preventScroll: true });
      }
    }
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [open, controlledOpen, onOpenChange]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = Array.from(
      dialogRef.current?.querySelectorAll<HTMLElement>(focusableSelector) ?? [],
    ).filter((element) => !element.hasAttribute("disabled"));
    if (focusable.length === 0) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        className="icon-button app-shell__drawer-trigger"
        type="button"
        aria-label={triggerLabel}
        title={triggerLabel}
        aria-expanded={open}
        onClick={() => setOpen(true)}
      >
        {triggerIcon ?? <PanelRightOpen aria-hidden="true" size={18} />}
      </button>
      {open ? (
        <div
          className="responsive-drawer__backdrop"
          data-testid="drawer-backdrop"
          onPointerDownCapture={(event) => {
            // A selection dragged out of the dialog can produce a click whose
            // target is the shared backdrop. Require a complete outside click.
            backdropPress.current = event.target === event.currentTarget && event.button === 0 && event.isPrimary !== false
              ? {pointerId:event.pointerId,x:event.clientX,y:event.clientY,moved:false,released:false} : null;
          }}
          onPointerMoveCapture={(event) => {
            const press=backdropPress.current;
            if(press && press.pointerId===event.pointerId && Math.hypot(event.clientX-press.x,event.clientY-press.y)>6) press.moved=true;
          }}
          onPointerUpCapture={(event) => {
            const press=backdropPress.current;
            if(press && press.pointerId===event.pointerId) press.released=event.target===event.currentTarget;
          }}
          onPointerCancelCapture={() => {backdropPress.current=null}}
          onClick={(event) => {
            const press=backdropPress.current;
            backdropPress.current=null;
            if (event.target === event.currentTarget && press?.released && !press.moved) {
              closeDrawer();
            }
          }}
        >
          <div
            ref={dialogRef}
            className={`responsive-drawer responsive-drawer--${side}${footer ? ' responsive-drawer--with-footer' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            onKeyDown={handleKeyDown}
          >
            <header className="responsive-drawer__header">
              <h2 id={titleId}>{title}</h2>
              <button
                className="icon-button"
                type="button"
                aria-label={`关闭${title}`}
                title={`关闭${title}`}
                onClick={closeDrawer}
              >
                <X aria-hidden="true" size={18} />
              </button>
            </header>
            <div className="responsive-drawer__content">{children}</div>
            {footer ? <div className="responsive-drawer__footer">{footer}</div> : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
