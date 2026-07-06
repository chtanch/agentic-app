import { useState } from "react";
import {
  Alert, Box, Button, Checkbox, Group, ScrollArea, Select, Stack, Text,
  TextInput, Textarea, Title, Tooltip,
} from "@mantine/core";
import { api, ApiError } from "../api/client.js";
import { TOOLS, usesFileTools } from "../lib/tools.js";
import { isTauri, pickDirectory } from "../lib/tauri.js";

// Agent editor (PRD §5.4 view 2): a plain form — name, system prompt, model
// dropdown, a checkbox per tool (the checkboxes ARE the tool assignment), and a
// workspace-folder field (text input + native folder picker) that sets the
// sandbox root for the file tools. Handles both create (initial=null) and edit
// (initial=Agent) against POST/PUT /agents (full replace, A.2.2).

export default function AgentEditor({ models, initial, onSaved, onCancel }) {
  const isEdit = initial != null;
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [modelId, setModelId] = useState(initial?.model_id ?? models[0]?.id ?? null);
  const [tools, setTools] = useState(initial?.tools ?? []);
  const [workspace, setWorkspace] = useState(initial?.workspace_folder ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const toggleTool = (name, on) =>
    setTools((prev) => (on ? [...new Set([...prev, name])] : prev.filter((t) => t !== name)));

  // §5.4 / PRD: the editor marks workspace as required whenever a file tool is
  // checked. (The backend still validates per-call, but we surface it up front.)
  const workspaceRequired = usesFileTools(tools);
  const workspaceMissing = workspaceRequired && workspace.trim() === "";
  const canSave =
    name.trim() !== "" && !!modelId && !workspaceMissing && !busy;

  const browse = async () => {
    const picked = await pickDirectory(workspace.trim() || undefined);
    if (picked) setWorkspace(picked);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    const body = {
      name: name.trim(),
      description: description.trim(),
      model_id: modelId,
      tools,
      workspace_folder: workspace.trim() || null,
    };
    try {
      const agent = isEdit
        ? await api.updateAgent(initial.id, body)
        : await api.createAgent(body);
      onSaved(agent);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  };

  return (
    <Stack h="100vh" gap={0}>
      <Group justify="space-between" p="sm" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
        <Title order={5}>{isEdit ? "Edit agent" : "New agent"}</Title>
      </Group>

      <ScrollArea style={{ flex: 1 }}>
        <Stack p="md" gap="md" maw={620}>
          <TextInput
            label="Name"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            required
          />
          <Textarea
            label="System prompt"
            description="Sent to the model as the agent's system prompt."
            autosize minRows={3} maxRows={12}
            value={description}
            onChange={(e) => setDescription(e.currentTarget.value)}
          />
          <Select
            label="Model"
            data={models.map((m) => ({ value: m.id, label: m.label }))}
            value={modelId}
            onChange={setModelId}
            allowDeselect={false}
            required
          />

          <Box>
            <Text fw={500} size="sm" mb={4}>Tools</Text>
            <Text c="dimmed" size="xs" mb="xs">
              Only the tools you check are offered to this agent's model.
            </Text>
            <Stack gap="xs">
              {TOOLS.map((t) => (
                <Checkbox
                  key={t.name}
                  checked={tools.includes(t.name)}
                  onChange={(e) => toggleTool(t.name, e.currentTarget.checked)}
                  label={t.label}
                  description={t.description}
                />
              ))}
            </Stack>
          </Box>

          <Box>
            <Group gap="xs" align="flex-end" wrap="nowrap">
              <TextInput
                style={{ flex: 1 }}
                label="Workspace folder"
                description="Sandbox root for the file tools. Required when a file tool is enabled."
                placeholder="C:\\path\\to\\workspace"
                value={workspace}
                onChange={(e) => setWorkspace(e.currentTarget.value)}
                required={workspaceRequired}
                error={workspaceMissing ? "Required because a file tool is enabled." : null}
              />
              {isTauri() ? (
                <Button variant="default" onClick={browse}>Browse…</Button>
              ) : (
                <Tooltip label="Native picker is available in the desktop app — paste a path here in dev." withArrow>
                  <Button variant="default" disabled>Browse…</Button>
                </Tooltip>
              )}
            </Group>
          </Box>

          {error && <Alert color="red" variant="light">{error}</Alert>}

          <Group>
            <Button onClick={submit} loading={busy} disabled={!canSave}>
              {isEdit ? "Save changes" : "Create agent"}
            </Button>
            <Button variant="subtle" onClick={onCancel} disabled={busy}>Cancel</Button>
          </Group>
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
