import "./ui.css";

interface InsetListProps {
  children: React.ReactNode;
  className?: string;
}

export function InsetList({ children, className = "" }: InsetListProps) {
  return <div className={`ui-inset-list ${className}`.trim()}>{children}</div>;
}

interface InsetRowProps {
  children: React.ReactNode;
  selected?: boolean;
  onClick?: () => void;
  className?: string;
  trailing?: React.ReactNode;
}

export function InsetRow({
  children,
  selected = false,
  onClick,
  className = "",
  trailing,
}: InsetRowProps) {
  const Tag = onClick ? "button" : "div";
  return (
    <Tag
      type={onClick ? "button" : undefined}
      className={`ui-inset-row${selected ? " ui-inset-row--selected" : ""}${onClick ? " ui-inset-row--clickable" : ""} ${className}`.trim()}
      onClick={onClick}
    >
      <span className="ui-inset-row__content">{children}</span>
      {trailing && <span className="ui-inset-row__trailing">{trailing}</span>}
    </Tag>
  );
}
