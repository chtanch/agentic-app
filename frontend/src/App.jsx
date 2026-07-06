import { useEffect, useRef, useState } from "react";
import {
  Alert, Box, Button, Center, Group, Loader, Modal, Paper, ScrollArea,
  Select, Stack, Text, TextInput, Textarea, Title,
} from "@mantine/core";
import { api, ApiError } from "./api/client.js";

// Phase 2: the first real frontend↔sidecar round-trip — single agent,
// non-streaming chat, no tools. A trivial two-pane UI (agent list + chat) that
// exercises the whole REST seam end to end. The full agent editor, tool cards
// and settings view are Phase 4.

export default function App() {
  const [ready, setReady] = useState(false); // sidecar health gate
  const [agents, setAgents] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [models, setModels] = useState([]);
  const [creating, setCreating] = useState(false);

  // Poll /health until the sidecar has bound its port (A.2.1), then load data.
  useEffect(() => {
    let active = true;
    const tick = async () => {
      try {
        await api.health();
        if (!active) return;
        setReady(true);
        const [ag, md] = await Promise.all([api.listAgents(), api.models()]);
        if (!active) return;
        setAgents(ag);
        setModels(md);
      } catch {
        if (active) setTimeout(tick, 1000);
      }
    };
    tick();
    return () => { active = false; };
  }, []);

  const refreshAgents = async () => setAgents(await api.listAgents());

  const onCreated = async (agent) => {
    setCreating(false);
    await refreshAgents();
    setSelectedId(agent.id);
  };

  const onDeleted = async (id) => {
    await api.deleteAgent(id);
    if (selectedId === id) setSelectedId(null);
    await refreshAgents();
  };

  if (!ready) {
    return (
      <Center h="100vh">
        <Stack align="center" gap="xs">
          <Loader />
          <Text c="dimmed">Starting the local backend…</Text>
        </Stack>
      </Center>
    );
  }

  return (
    <Group h="100vh" gap={0} align="stretch" wrap="nowrap">
      <Box w={260} p="md" style={{ borderRight: "1px solid var(--mantine-color-default-border)", overflowY: "auto" }}>
        <Group justify="space-between" mb="sm">
          <Title order={4}>Agents</Title>
          <Button size="xs" onClick={() => setCreating(true)}>New</Button>
        </Group>
        <Stack gap={4}>
          {agents.length === 0 && <Text c="dimmed" size="sm">No agents yet.</Text>}
          {agents.map((a) => (
            <Group key={a.id} justify="space-between" wrap="nowrap">
              <Button
                variant={a.id === selectedId ? "filled" : "subtle"}
                size="sm"
                justify="flex-start"
                style={{ flex: 1 }}
                onClick={() => setSelectedId(a.id)}
              >
                {a.name}
              </Button>
              <Button variant="subtle" color="red" size="compact-sm" onClick={() => onDeleted(a.id)}>✕</Button>
            </Group>
          ))}
        </Stack>
      </Box>

      <Box style={{ flex: 1, minWidth: 0 }}>
        {selectedId == null
          ? <Center h="100%"><Text c="dimmed">Select or create an agent to start chatting.</Text></Center>
          : <ChatView key={selectedId} agentId={selectedId} />}
      </Box>

      <Modal opened={creating} onClose={() => setCreating(false)} title="New agent" centered>
        <CreateAgentForm models={models} onCreated={onCreated} />
      </Modal>
    </Group>
  );
}

function CreateAgentForm({ models, onCreated }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [modelId, setModelId] = useState(models[0]?.id ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const agent = await api.createAgent({
        name: name.trim(),
        description: description.trim(),
        model_id: modelId,
        tools: [],            // no tools in Phase 2
        workspace_folder: null,
      });
      await onCreated(agent);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong.");
      setBusy(false);
    }
  };

  return (
    <Stack>
      <TextInput label="Name" value={name} onChange={(e) => setName(e.currentTarget.value)} required />
      <Textarea
        label="System prompt"
        description="Sent as the agent's system prompt."
        autosize minRows={2}
        value={description}
        onChange={(e) => setDescription(e.currentTarget.value)}
      />
      <Select
        label="Model"
        data={models.map((m) => ({ value: m.id, label: m.label }))}
        value={modelId}
        onChange={setModelId}
        allowDeselect={false}
      />
      {error && <Alert color="red" variant="light">{error}</Alert>}
      <Button onClick={submit} loading={busy} disabled={!name.trim() || !modelId}>Create</Button>
    </Stack>
  );
}

function ChatView({ agentId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const viewport = useRef(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.listMessages(agentId)
      .then((m) => { if (active) setMessages(m); })
      .catch(() => { if (active) setError({ kind: "offline", message: "Couldn't load history." }); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [agentId]);

  useEffect(() => {
    // Autoscroll to the newest message / the thinking indicator.
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  const send = async () => {
    const text = input.trim();
    if (!text || thinking) return;
    setInput("");
    setError(null);
    // Optimistic user bubble (instant feedback on a slow non-streaming turn).
    const optimistic = { id: `tmp-${Date.now()}`, role: "user", content: text, _optimistic: true };
    setMessages((prev) => [...prev, optimistic]);
    setThinking(true);
    try {
      const newRows = await api.sendMessage(agentId, text);
      // Replace the optimistic bubble with the canonical rows the server
      // returned (user + assistant), keyed by their real ids (A.2.4).
      setMessages((prev) => [...prev.filter((m) => !m._optimistic), ...newRows]);
    } catch (e) {
      setMessages((prev) => prev.filter((m) => !m._optimistic));
      setInput(text); // let the user retry without retyping
      setError(e instanceof ApiError ? e : new ApiError("offline", "Something went wrong."));
    } finally {
      setThinking(false);
    }
  };

  const clear = async () => {
    await api.clearMessages(agentId);
    setMessages([]);
    setError(null);
  };

  // `tool` rows are not rendered as their own bubble (A.2.3) — Phase 2 has none.
  const bubbles = messages.filter((m) => m.role === "user" || m.role === "assistant");

  return (
    <Stack h="100vh" gap={0}>
      <Group justify="space-between" p="sm" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
        <Title order={5}>Chat</Title>
        <Button size="xs" variant="subtle" color="red" onClick={clear} disabled={messages.length === 0}>
          Clear conversation
        </Button>
      </Group>

      <ScrollArea style={{ flex: 1 }} viewportRef={viewport}>
        <Stack p="md" gap="sm">
          {loading && <Center><Loader size="sm" /></Center>}
          {!loading && bubbles.length === 0 && <Text c="dimmed" ta="center">Say hello to your agent.</Text>}
          {bubbles.map((m) => <Bubble key={m.id} role={m.role} content={m.content} />)}
          {thinking && (
            <Group gap="xs" pl="sm">
              <Loader size="xs" type="dots" />
              <Text c="dimmed" size="sm">thinking…</Text>
            </Group>
          )}
          {error && (
            <Alert color="red" variant="light" title={errorTitle(error.kind)}>{error.message}</Alert>
          )}
        </Stack>
      </ScrollArea>

      <Group p="sm" gap="xs" align="flex-end" style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}>
        <Textarea
          style={{ flex: 1 }}
          placeholder="Type a message…  (Enter to send, Shift+Enter for newline)"
          autosize minRows={1} maxRows={6}
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
          disabled={thinking}
        />
        <Button onClick={send} loading={thinking} disabled={!input.trim()}>Send</Button>
      </Group>
    </Stack>
  );
}

function Bubble({ role, content }) {
  const isUser = role === "user";
  return (
    <Group justify={isUser ? "flex-end" : "flex-start"}>
      <Paper
        p="sm" radius="md" withBorder
        bg={isUser ? "var(--mantine-color-blue-light)" : "var(--mantine-color-default)"}
        maw="80%"
      >
        <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{(content ?? "").trim()}</Text>
      </Paper>
    </Group>
  );
}

function errorTitle(kind) {
  switch (kind) {
    case "bad_api_key": return "API key problem";
    case "offline": return "Offline";
    case "model_error": return "Model error";
    default: return "Error";
  }
}
