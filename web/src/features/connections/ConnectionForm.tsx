import { useState, type FormEvent } from "react";
import { ApiError } from "../../api/client";
import { Button } from "../../components/ui/Button";
import { Dialog } from "../../components/ui/Dialog";
import { Field } from "../../components/ui/Field";
import { relativeTime } from "../../lib/time";
import type { Connection, ConnectionInput, SystemsResponse } from "./api";
import { FirmSelect } from "./FirmSelect";

type Errors = Partial<Record<keyof ConnectionInput | "form", string>>;

export function ConnectionForm({
  open,
  editing,
  systems,
  systemsError,
  onClose,
  onSubmit,
}: {
  open: boolean;
  editing: Connection | null;
  systems: SystemsResponse | undefined;
  systemsError: Error | null;
  onClose: () => void;
  onSubmit: (input: ConnectionInput) => Promise<void>;
}) {
  const [firm, setFirm] = useState(editing?.system_name ?? "");
  const [username, setUsername] = useState(editing?.username ?? "");
  const [password, setPassword] = useState("");
  const [showTest, setShowTest] = useState(
    editing ? (systems?.systems.find((s) => s.name === editing.system_name)?.is_test ?? false) : false,
  );
  const [errors, setErrors] = useState<Errors>({});
  const [saving, setSaving] = useState(false);

  function validate(): Errors {
    const found: Errors = {};
    if (!firm) found.system_name = "Choose a firm from the list.";
    if (!username.trim()) found.username = "Enter the Rithmic username.";
    if (!editing && !password) found.password = "Enter the Rithmic password.";
    return found;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length) return;
    setSaving(true);
    try {
      await onSubmit({ system_name: firm, username: username.trim(), password });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setErrors({ username: "A connection for this firm and username already exists." });
      } else if (error instanceof ApiError && Object.keys(error.fieldErrors).length) {
        setErrors(error.fieldErrors as Errors);
      } else {
        setErrors({ form: error instanceof Error ? error.message : "Could not save" });
      }
    } finally {
      setSaving(false);
    }
  }

  const firms = systems?.systems ?? [];
  return (
    <Dialog
      open={open}
      title={editing ? "Edit connection" : "Add connection"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="connection-form" busy={saving}>
            {editing ? "Save changes" : "Add connection"}
          </Button>
        </>
      }
    >
      <form id="connection-form" className="form" onSubmit={submit} noValidate>
        {systems?.cached && (
          <p className="banner" role="status">
            Rithmic's firm list couldn't be refreshed. Showing the list from{" "}
            {relativeTime(systems.fetched_at)}.
          </p>
        )}
        {systemsError && (
          <p className="banner banner-error" role="alert">
            The firm list is unavailable: {systemsError.message}
          </p>
        )}
        <Field label="Firm" error={errors.system_name}>
          {(props) => (
            <FirmSelect
              firms={firms}
              value={firm}
              onChange={setFirm}
              showTest={showTest}
              inputProps={props}
            />
          )}
        </Field>
        <label className="checkbox">
          <input type="checkbox" checked={showTest} onChange={(event) => setShowTest(event.target.checked)} />
          Show test systems
        </label>
        <Field label="Username" error={errors.username}>
          {(props) => (
            <input
              {...props}
              className="input"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          )}
        </Field>
        <Field
          label="Password"
          error={errors.password}
          hint={
            editing ? "Leave blank to keep the saved password." : "Stored encrypted. It is never shown again."
          }
        >
          {(props) => (
            <input
              {...props}
              className="input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          )}
        </Field>
        {errors.form && (
          <p className="field-error" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}
