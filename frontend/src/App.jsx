import { useEffect, useState } from "react";
import {
  ActionIcon, Box, Button, Center, Group, Loader, Stack, Text, Title, Tooltip,
} from "@mantine/core";
import { api } from "./api/client.js";
import AgentEditor from "./components/AgentEditor.jsx";
import ChatView from "./components/ChatView.jsx";
import SettingsModal from "./components/SettingsModal.jsx";

// Phase 4 — the full frontend build-out (PRD §5.4): agent list, agent editor
// (form + tool checkboxes + workspace), chat view with tool-call cards and
// "Clear conversation", plus a settings view for API keys. A two-pane shell:
// the sidebar lists agents; the main pane shows either the chat or the editor.

export default function App() {
  const [ready, setReady] = useState(false); // sidecar health gate
  const [agents, setAgents] = useState([]);
  const [models, setModels] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  // Main-pane mode: { type: "chat" } | { type: "new" } | { type: "edit", agent }
  const [pane, setPane] = useState({ type: "chat" });
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Poll /health until the sidecar has bound its port (A.2.1), then load data.
  useEffect(() => {
    let active = true;
    const tick = async () => {
      try {
        await api.health();
        if (!active) return;
        const [ag, md] = await Promise.all([api.listAgents(), api.models()]);
        if (!active) return;
        setAgents(ag);
        setModels(md);
        setReady(true);
      } catch {
        if (active) setTimeout(tick, 1000);
      }
    };
    tick();
    return () => { active = false; };
  }, []);

  const refreshAgents = () => api.listAgents().then(setAgents);

  const openChat = (id) => { setSelectedId(id); setPane({ type: "chat" }); };
  const openNew = () => setPane({ type: "new" });
  const openEdit = async (id) => {
    const agent = await api.getAgent(id); // full config for the form
    setSelectedId(id);
    setPane({ type: "edit", agent });
  };

  const onSaved = async (agent) => {
    await refreshAgents();
    setSelectedId(agent.id);
    setPane({ type: "chat" });
  };

  const onDeleted = async (id) => {
    await api.deleteAgent(id);
    await refreshAgents();
    if (selectedId === id) { setSelectedId(null); setPane({ type: "chat" }); }
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
      <Box
        w={260} p="md"
        style={{ borderRight: "1px solid var(--mantine-color-default-border)", display: "flex", flexDirection: "column" }}
      >
        <Group justify="space-between" mb="sm">
          <Title order={4}>Agents</Title>
          <Button size="xs" onClick={openNew}>New</Button>
        </Group>

        <Stack gap={4} style={{ flex: 1, overflowY: "auto" }}>
          {agents.length === 0 && <Text c="dimmed" size="sm">No agents yet.</Text>}
          {agents.map((a) => {
            const active = a.id === selectedId;
            return (
              <Group key={a.id} justify="space-between" wrap="nowrap" gap={2}>
                <Button
                  variant={active ? "filled" : "subtle"}
                  size="sm" justify="flex-start"
                  style={{ flex: 1, minWidth: 0 }}
                  onClick={() => openChat(a.id)}
                >
                  <Text truncate>{a.name}</Text>
                </Button>
                <Tooltip label="Edit" withArrow>
                  <ActionIcon variant="subtle" color="gray" onClick={() => openEdit(a.id)} aria-label="Edit agent">
                    ✎
                  </ActionIcon>
                </Tooltip>
                <Tooltip label="Delete" withArrow>
                  <ActionIcon variant="subtle" color="red" onClick={() => onDeleted(a.id)} aria-label="Delete agent">
                    ✕
                  </ActionIcon>
                </Tooltip>
              </Group>
            );
          })}
        </Stack>

        <Button variant="subtle" color="gray" size="xs" mt="sm" onClick={() => setSettingsOpen(true)}>
          ⚙ Settings
        </Button>
      </Box>

      <Box style={{ flex: 1, minWidth: 0 }}>
        <MainPane
          pane={pane}
          models={models}
          selectedId={selectedId}
          agents={agents}
          onSaved={onSaved}
          onCancel={() => setPane({ type: "chat" })}
          onEdit={openEdit}
        />
      </Box>

      <SettingsModal opened={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </Group>
  );
}

function MainPane({ pane, models, selectedId, agents, onSaved, onCancel, onEdit }) {
  if (pane.type === "new") {
    return <AgentEditor models={models} initial={null} onSaved={onSaved} onCancel={onCancel} />;
  }
  if (pane.type === "edit") {
    return (
      <AgentEditor
        key={pane.agent.id}
        models={models}
        initial={pane.agent}
        onSaved={onSaved}
        onCancel={onCancel}
      />
    );
  }
  if (selectedId == null) {
    return (
      <Center h="100%">
        <Text c="dimmed">Select or create an agent to start chatting.</Text>
      </Center>
    );
  }
  const name = agents.find((a) => a.id === selectedId)?.name ?? "Chat";
  return (
    <ChatView key={selectedId} agentId={selectedId} agentName={name} onEdit={() => onEdit(selectedId)} />
  );
}
