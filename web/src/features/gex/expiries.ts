const expiryDate = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

export function formatExpiry(yyyymmdd: string): string {
  return expiryDate.format(
    new Date(
      Date.UTC(Number(yyyymmdd.slice(0, 4)), Number(yyyymmdd.slice(4, 6)) - 1, Number(yyyymmdd.slice(6))),
    ),
  );
}

/** "Next: Nov 12", "Next 2 (to Nov 13)", ... "All 4 (to Nov 17)". */
export function expiryOptions(available: string[]): { value: string; label: string }[] {
  const last = available.at(-1) ?? "";
  return [
    ...available.slice(0, -1).map((expiry, index) => ({
      value: String(index + 1),
      label:
        index === 0
          ? `Next expiry: ${formatExpiry(expiry)}`
          : `Next ${index + 1} (to ${formatExpiry(expiry)})`,
    })),
    { value: "0", label: `All ${available.length} expiries (to ${formatExpiry(last)})` },
  ];
}
