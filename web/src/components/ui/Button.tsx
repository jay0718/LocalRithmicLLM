import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "normal" | "small";
  busy?: boolean;
};

export function Button({
  variant = "secondary",
  size = "normal",
  busy = false,
  className,
  disabled,
  ...rest
}: Props) {
  const classes = ["button", `button-${variant}`, size === "small" && "button-small", className]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type="button"
      {...rest}
      className={classes}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
    />
  );
}
