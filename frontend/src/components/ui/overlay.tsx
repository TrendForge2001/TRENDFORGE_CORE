"use client";

import { Dialog } from "@base-ui/react/dialog";
import { Popover } from "@base-ui/react/popover";
import { X } from "lucide-react";
import type { ReactNode } from "react";

export function Overlay({
  open,
  onClose,
  title,
  description,
  children,
  side = false,
  wide = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  side?: boolean;
  wide?: boolean;
}) {
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(value) => {
        if (!value) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Backdrop className="backdrop" />
        <Dialog.Popup
          className={`dialog ${side ? "drawer" : ""} ${wide ? "wide" : ""}`}
        >
          <header className="dialog-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {description && (
                <Dialog.Description>{description}</Dialog.Description>
              )}
            </div>
            <Dialog.Close className="icon-button" aria-label="Close">
              <X size={18} />
            </Dialog.Close>
          </header>
          <div className="dialog-body">{children}</div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ContextPopover({
  label,
  children,
  className = "button",
  onTrigger,
  pressed,
}: {
  label: ReactNode;
  children: ReactNode;
  className?: string;
  onTrigger?: () => void;
  pressed?: boolean;
}) {
  return (
    <Popover.Root>
      <Popover.Trigger
        className={className}
        onClick={onTrigger}
        aria-pressed={pressed}
      >
        {label}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner
          sideOffset={8}
          align="end"
          className="popover-positioner"
        >
          <Popover.Popup className="popover">{children}</Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
