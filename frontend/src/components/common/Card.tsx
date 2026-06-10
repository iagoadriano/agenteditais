import type { ReactNode, CSSProperties } from "react";
import { HelpCircle } from "lucide-react";

interface CardProps {
  title?: string;
  subtitle?: string;
  icon?: ReactNode;
  children: ReactNode;
  actions?: ReactNode;
  variant?: "default" | "attention" | "success" | "warning";
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  helpText?: string;
  style?: CSSProperties;
}

export function Card({
  title,
  subtitle,
  icon,
  children,
  actions,
  variant = "default",
  helpText,
  style,
}: CardProps) {
  return (
    <div className={`card card-${variant}`} style={style}>
      {(title || actions) && (
        <div className="card-header">
          <div className="card-header-left">
            {icon && <span className="card-icon">{icon}</span>}
            <div className="card-titles">
              {title && <h3 className="card-title">{title}</h3>}
              {subtitle && <p className="card-subtitle">{subtitle}</p>}
            </div>
          </div>
          <div className="card-header-right">
            {helpText && (
              <button className="card-help-btn" title={helpText}>
                <HelpCircle size={16} />
              </button>
            )}
            {actions}
          </div>
        </div>
      )}
      <div className="card-content">{children}</div>
    </div>
  );
}

interface StatCardProps {
  icon: ReactNode;
  value: string | number;
  label: string;
  trend?: { value: number; label: string };
  color?: "blue" | "green" | "yellow" | "red" | "purple" | "orange";
}

export function StatCard({ icon, value, label, trend, color = "blue" }: StatCardProps) {
  return (
    <div className={`stat-card stat-card-${color}`}>
      <div className="stat-card-icon">{icon}</div>
      <div className="stat-card-content">
        <span className="stat-card-value">{value}</span>
        <span className="stat-card-label">{label}</span>
        {trend && (
          <span className={`stat-card-trend ${trend.value >= 0 ? "positive" : "negative"}`}>
            {trend.value >= 0 ? "+" : ""}{trend.value}% {trend.label}
          </span>
        )}
      </div>
    </div>
  );
}
