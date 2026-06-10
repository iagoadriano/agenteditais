import type { ReactNode } from "react";

interface ActionBarProps {
  children: ReactNode;
  position?: "top" | "bottom";
}

export function ActionBar({ children, position = "top" }: ActionBarProps) {
  return (
    <div className={`action-bar action-bar-${position}`}>
      {children}
    </div>
  );
}

interface ActionButtonProps {
  icon?: ReactNode;
  label: string;
  onClick: () => void;
  // "neutral", "outline" e "warning" já eram usados em runtime pelas pages
  variant?: "primary" | "secondary" | "danger" | "success" | "neutral" | "outline" | "warning";
  disabled?: boolean;
  loading?: boolean;
  size?: "sm" | "md";
}

export function ActionButton({
  icon,
  label,
  onClick,
  variant = "secondary",
  disabled = false,
  loading = false,
  size = "md",
}: ActionButtonProps) {
  return (
    <button
      className={`action-button action-button-${variant}`}
      style={size === "sm" ? { padding: "4px 10px", fontSize: 12 } : undefined}
      onClick={onClick}
      disabled={disabled || loading}
    >
      {loading ? (
        <span className="loading-spinner small" />
      ) : (
        icon && <span className="action-button-icon">{icon}</span>
      )}
      <span>{label}</span>
    </button>
  );
}
