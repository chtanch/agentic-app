import { useEffect, useState } from "react";
import {
  Alert, Badge, Button, Group, Modal, PasswordInput, Stack, Text,
} from "@mantine/core";
import { api, ApiError } from "../api/client.js";

// Settings view (PRD §5.6): one input per provider for API keys, writing to the
// api_keys table via PUT /keys. GET /keys returns presence only (never the key
// value). Keys can also come from a config file, which wins on precedence at
// sidecar startup — so we only surface set/unset here, and leave the empty
// input meaning "leave unchanged".

const PROVIDERS = [
  { key: "openrouter", label: "OpenRouter API key", placeholder: "sk-or-…",
    hint: "Required for chat — the model provider." },
  { key: "tavily", label: "Tavily API key", placeholder: "tvly-…",
    hint: "Only needed if an agent uses the Web Search tool." },
];

export default function SettingsModal({ opened, onClose }) {
  const [status, setStatus] = useState(null); // { openrouter, tavily } presence
  const [values, setValues] = useState({ openrouter: "", tavily: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!opened) return;
    setError(null);
    setSaved(false);
    setValues({ openrouter: "", tavily: "" });
    api.getKeys().then(setStatus).catch(() => setStatus(null));
  }, [opened]);

  const save = async () => {
    // Send only the providers the user actually typed a value for.
    const body = {};
    for (const p of PROVIDERS) {
      const v = values[p.key].trim();
      if (v !== "") body[p.key] = v;
    }
    if (Object.keys(body).length === 0) { onClose(); return; }
    setBusy(true);
    setError(null);
    try {
      const next = await api.putKeys(body);
      setStatus(next);
      setValues({ openrouter: "", tavily: "" });
      setSaved(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Couldn't save keys.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal opened={opened} onClose={onClose} title="Settings — API keys" centered>
      <Stack>
        <Text c="dimmed" size="sm">
          Keys are stored locally. A config file can also supply them and takes
          precedence over anything entered here.
        </Text>
        {PROVIDERS.map((p) => (
          <PasswordInput
            key={p.key}
            label={
              <Group gap="xs">
                <span>{p.label}</span>
                {status && (
                  <Badge size="xs" variant="light" color={status[p.key] === "set" ? "green" : "gray"}>
                    {status[p.key] === "set" ? "configured" : "not set"}
                  </Badge>
                )}
              </Group>
            }
            description={p.hint}
            placeholder={status?.[p.key] === "set" ? "•••••••• (leave blank to keep)" : p.placeholder}
            value={values[p.key]}
            onChange={(e) => setValues((v) => ({ ...v, [p.key]: e.currentTarget.value }))}
          />
        ))}
        {error && <Alert color="red" variant="light">{error}</Alert>}
        {saved && !error && <Alert color="green" variant="light">Saved.</Alert>}
        <Group justify="flex-end">
          <Button variant="subtle" onClick={onClose}>Close</Button>
          <Button onClick={save} loading={busy}>Save</Button>
        </Group>
      </Stack>
    </Modal>
  );
}
