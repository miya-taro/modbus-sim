import type { ReactNode } from "react";

export function Modal({
  title,
  children,
  onClose,
  onOk,
  okLabel = "OK",
  okDisabled,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  onOk?: () => void;
  okLabel?: string;
  okDisabled?: boolean;
}) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <h3>{title}</h3>
        {children}
        <div className="actions">
          <button onClick={onClose}>キャンセル</button>
          {onOk && (
            <button className="primary" onClick={onOk} disabled={okDisabled}>
              {okLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
