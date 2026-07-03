# Project: Windows Agentic Desktop App

## What this is
Tauri (Rust shell) + Python Flask sidecar + React/Mantine frontend.
Python packages should be managed using uv.
Full spec in docs/: main PRD + Appendix A (arch/REST/turn-loop) + Appendix B (tools).
Delivery target: 1 week. Prefer the spec's simpler chosen path over "better" ideas.

## Hard rules
- Appendix A §A.2 (REST), §A.3.2 (turn loop), Appendix B §B.1/§B.5 (tool types,
  call site) are CONTRACTS. Implement near-verbatim. Don't redesign them. Ask me if you spot any issues.
- Decisions Log (PRD §7) is settled. Don't relitigate non-streaming, plaintext
  key storage, full-file-overwrite edits, one-conversation-per-agent, etc.
- Sidecar binds 127.0.0.1 ONLY, never 0.0.0.0.
- API keys never logged, never returned by GET /keys (presence only).
- message_json stores the FULL raw provider message verbatim; replay it
  unmodified and in order (reasoning_details included). Never cherry-pick fields.
- Tool errors are data, not exceptions: recoverable -> error string to model;
  unexpected raise -> caught, logged, safe string; turn never aborts.
- Tool loop is multi-round (while-loop + continue) with a max-iterations guard.
- File sandbox enforced inside handlers, per-agent workspace_folder.

## Workflow
- Build one PRD §8 phase at a time. Stop at phase boundaries and wait.
- Match the §5.5 SQL schema and A.2 endpoint shapes exactly.
- Commit per working phase. Note any spec deviation explicitly and why.