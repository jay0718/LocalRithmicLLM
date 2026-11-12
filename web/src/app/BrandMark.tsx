/** The mark: a price level with one node on it, drawn in the current ink. */
export function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 20 20" aria-hidden="true">
      <rect x="1" y="9.25" width="18" height="1.5" rx="0.75" />
      <circle cx="12.5" cy="10" r="3.25" />
    </svg>
  );
}
