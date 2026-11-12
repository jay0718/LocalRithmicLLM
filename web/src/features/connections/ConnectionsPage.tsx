import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { PageHeader } from "../../components/PageHeader";
import { Table, type Column } from "../../components/ui/Table";
import { useToast } from "../../components/ui/toast";
import { relativeTime } from "../../lib/time";
import { useResource } from "../../lib/useResource";
import {
  createConnection,
  deleteConnection,
  listConnections,
  listSystems,
  updateConnection,
  type Connection,
  type ConnectionInput,
} from "./api";
import { ConnectionForm } from "./ConnectionForm";

const STATUS_LABELS: Record<string, string> = { untested: "Not tested", ok: "Working", rejected: "Rejected" };

function StatusBadge({ status }: { status: string }) {
  return <span className={`status status-${status}`}>{STATUS_LABELS[status] ?? status}</span>;
}

export function ConnectionsPage() {
  const connections = useResource(listConnections);
  const systems = useResource(listSystems);
  const toast = useToast();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Connection | null>(null);
  const [deleting, setDeleting] = useState<Connection | null>(null);
  const [busyDelete, setBusyDelete] = useState(false);
  const [formKey, setFormKey] = useState(0);

  function openForm(connection: Connection | null) {
    setEditing(connection);
    setFormKey((key) => key + 1);
    setFormOpen(true);
  }

  async function save(input: ConnectionInput) {
    if (editing) await updateConnection(editing.id, input);
    else await createConnection(input);
    setFormOpen(false);
    toast("success", editing ? "Connection updated" : "Connection added");
    await connections.reload();
  }

  async function confirmDelete() {
    if (!deleting) return;
    setBusyDelete(true);
    try {
      await deleteConnection(deleting.id);
      toast("success", `Deleted ${deleting.system_name} · ${deleting.username}`);
      setDeleting(null);
      await connections.reload();
    } catch (error) {
      toast("error", error instanceof Error ? error.message : "Could not delete");
    } finally {
      setBusyDelete(false);
    }
  }

  const columns: Column<Connection>[] = [
    { key: "firm", header: "Firm", render: (row) => <strong>{row.system_name}</strong> },
    { key: "username", header: "Username", render: (row) => <span className="mono">{row.username}</span> },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    {
      key: "checked",
      header: "Last check",
      render: (row) =>
        row.last_checked_at ? relativeTime(row.last_checked_at) : <span className="muted">Never</span>,
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      render: (row) => (
        <div className="row-actions">
          <Button
            size="small"
            onClick={() => openForm(row)}
            aria-label={`Edit ${row.system_name} ${row.username}`}
          >
            Edit
          </Button>
          <Button
            size="small"
            variant="ghost"
            onClick={() => setDeleting(row)}
            aria-label={`Delete ${row.system_name} ${row.username}`}
          >
            Delete
          </Button>
        </div>
      ),
    },
  ];

  const rows = connections.data ?? [];
  const firstLoad = connections.loading && !connections.data;
  return (
    <>
      <PageHeader
        title="Connections"
        description="Rithmic logins for market data · passwords are encrypted"
        actions={
          rows.length > 0 && (
            <Button variant="primary" onClick={() => openForm(null)}>
              Add connection
            </Button>
          )
        }
      />
      {connections.error && (
        <div className="banner banner-error" role="alert">
          Couldn't load connections: {connections.error.message}{" "}
          <Button size="small" onClick={() => void connections.reload()}>
            Try again
          </Button>
        </div>
      )}
      {!firstLoad && !connections.error && rows.length === 0 ? (
        <div className="card empty">
          <h2>No connections yet</h2>
          <p className="muted">
            Add a Rithmic login from your prop firm or broker to start collecting market data.
          </p>
          <Button variant="primary" onClick={() => openForm(null)}>
            Add connection
          </Button>
        </div>
      ) : (
        !connections.error && (
          <Table
            caption="Rithmic connections"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            loading={firstLoad}
          />
        )
      )}

      <ConnectionForm
        key={formKey}
        open={formOpen}
        editing={editing}
        systems={systems.data}
        systemsError={systems.error}
        onClose={() => setFormOpen(false)}
        onSubmit={save}
      />

      <Dialog
        open={deleting !== null}
        title="Delete connection?"
        onClose={() => setDeleting(null)}
        footer={
          <>
            <Button onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" busy={busyDelete} onClick={() => void confirmDelete()}>
              Delete
            </Button>
          </>
        }
      >
        {deleting && (
          <p>
            This removes <strong>{deleting.system_name}</strong> ·{" "}
            <span className="mono">{deleting.username}</span> and its saved password. Collection using it will
            stop.
          </p>
        )}
      </Dialog>
    </>
  );
}
