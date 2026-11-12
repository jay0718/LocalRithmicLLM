import { Table, type Column } from "../../components/ui/Table";
import { formatGex, formatStrike } from "./format";
import type { StrikeGex } from "./types";

const columns: Column<StrikeGex>[] = [
  {
    key: "strike",
    header: "Strike",
    render: (row) => <span className="num">{formatStrike(row.strike)}</span>,
  },
  {
    key: "calls",
    header: "Calls",
    align: "right",
    render: (row) => <span className="num">{formatGex(row.call_gex)}</span>,
  },
  {
    key: "puts",
    header: "Puts",
    align: "right",
    render: (row) => <span className="num">{formatGex(row.put_gex)}</span>,
  },
  {
    key: "net",
    header: "Net",
    align: "right",
    render: (row) => <span className="num">{formatGex(row.net_gex)}</span>,
  },
];

export function GexTable({ rows }: { rows: StrikeGex[] }) {
  return <Table caption="GEX by strike" columns={columns} rows={rows} rowKey={(row) => row.strike} />;
}
