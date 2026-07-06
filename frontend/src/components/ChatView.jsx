import { useEffect, useRef, useState } from "react";
import {
  Alert, Badge, Box, Button, Card, Center, Code, Collapse, Group, Loader,
  Paper, ScrollArea, Stack, Text, Textarea, Title,
} from "@mantine/core";
import { api, ApiError } from "../api/client.js";
import { toolLabel } from "../lib/tools.js";

// Chat view (PRD §5.4 view 3): message history, input box, "Clear
// conversation", and — new in Phase 4 — tool-call cards. Chat is non-streaming,
// so a whole turn (assistant text + any tool rounds) arrives at once and the
// cards render as already-resolved static elements (§5.4).

export default function ChatView({ agentId, agentName, onEdit }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const viewport = useRef(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api.listMessages(agentId)
      .then((m) => { if (active) setMessages(m); })
      .catch(() => { if (active) setError(new ApiError("offline", "Couldn't load history.")); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [agentId]);

  useEffect(() => {
    viewport.current?.scrollTo({ top: viewport.current.scrollHeight, behavior: "smooth" });
  }, [messages, thinking]);

  const send = async () => {
    const text = input.trim();
    if (!text || thinking) return;
    setInput("");
    setError(null);
    const optimistic = { id: `tmp-${Date.now()}`, role: "user", content: text, _optimistic: true };
    setMessages((prev) => [...prev, optimistic]);
    setThinking(true);
    try {
      const newRows = await api.sendMessage(agentId, text);
      // Replace the optimistic bubble with the canonical rows this turn produced
      // (user + any tool rows + final assistant), keyed by their real ids (A.2.4).
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

  const items = renderTimeline(messages);

  return (
    <Stack h="100vh" gap={0}>
      <Group justify="space-between" p="sm" style={{ borderBottom: "1px solid var(--mantine-color-default-border)" }}>
        <Title order={5} style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {agentName}
        </Title>
        <Group gap="xs" wrap="nowrap">
          <Button size="xs" variant="default" onClick={onEdit}>Edit agent</Button>
          <Button size="xs" variant="subtle" color="red" onClick={clear} disabled={messages.length === 0}>
            Clear conversation
          </Button>
        </Group>
      </Group>

      <ScrollArea style={{ flex: 1 }} viewportRef={viewport}>
        <Stack p="md" gap="sm">
          {loading && <Center><Loader size="sm" /></Center>}
          {!loading && items.length === 0 && <Text c="dimmed" ta="center">Say hello to your agent.</Text>}
          {items}
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

// Turn a flat message list into ordered render items. `user`/`assistant` text
// become bubbles; an assistant row's `tool_calls` become cards, each paired
// with its tool-result row (matched by tool_call_id). `tool` rows are never a
// bubble of their own — their output is surfaced inside the card (A.2.3).
function renderTimeline(messages) {
  const resultById = {};
  for (const m of messages) {
    if (m.role === "tool" && m.tool_call_id != null) resultById[m.tool_call_id] = m.content;
  }

  const items = [];
  for (const m of messages) {
    if (m.role === "user") {
      items.push(<Bubble key={m.id} role="user" content={m.content} />);
    } else if (m.role === "assistant") {
      if ((m.content ?? "").trim() !== "") {
        items.push(<Bubble key={`${m.id}-text`} role="assistant" content={m.content} />);
      }
      for (const call of m.tool_calls ?? []) {
        items.push(<ToolCallCard key={`${m.id}-${call.id}`} call={call} result={resultById[call.id]} />);
      }
    }
    // role === "tool": skipped — folded into the card above.
  }
  return items;
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

function ToolCallCard({ call, result }) {
  const [open, setOpen] = useState(false);
  const fn = call.function ?? {};
  const name = fn.name ?? "tool";
  const pending = result === undefined; // shouldn't happen (non-streaming), but be safe
  const isError = typeof result === "string" && result.startsWith("Error");

  return (
    <Card withBorder radius="md" padding="xs" bg="var(--mantine-color-default-hover)">
      <Group
        justify="space-between" wrap="nowrap"
        style={{ cursor: "pointer" }}
        onClick={() => setOpen((o) => !o)}
      >
        <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
          <Text size="xs" c="dimmed">🔧</Text>
          <Text size="sm" fw={500} truncate>{toolLabel(name)}</Text>
        </Group>
        <Group gap="xs" wrap="nowrap">
          <Badge size="sm" variant="light" color={pending ? "gray" : isError ? "red" : "green"}>
            {pending ? "no result" : isError ? "error" : "ok"}
          </Badge>
          <Text size="xs" c="dimmed">{open ? "▲" : "▼"}</Text>
        </Group>
      </Group>

      <Collapse in={open}>
        <Stack gap={6} mt="xs">
          <Field label="Arguments"><Pre>{prettyArgs(fn.arguments)}</Pre></Field>
          <Field label="Result"><Pre>{pending ? "(no result returned)" : result}</Pre></Field>
        </Stack>
      </Collapse>
    </Card>
  );
}

function Field({ label, children }) {
  return (
    <Box>
      <Text size="xs" c="dimmed" mb={2}>{label}</Text>
      {children}
    </Box>
  );
}

function Pre({ children }) {
  return (
    <Code block style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{children}</Code>
  );
}

// tool_calls[i].function.arguments is a JSON-encoded string (OpenAI/OpenRouter
// shape). Pretty-print it when it parses; otherwise show it verbatim.
function prettyArgs(raw) {
  if (raw == null || raw === "") return "{}";
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    return String(raw);
  }
}

function errorTitle(kind) {
  switch (kind) {
    case "bad_api_key": return "API key problem";
    case "offline": return "Offline";
    case "model_error": return "Model error";
    default: return "Error";
  }
}
