import "./ui.css";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: "sm" | "md" | "lg";
}

export default function Card({ children, className = "", padding = "md" }: CardProps) {
  return (
    <div className={`ui-card ui-card--${padding} ${className}`.trim()}>
      {children}
    </div>
  );
}
