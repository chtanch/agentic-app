## Design decisions & trade-offs
Major design decisions & trade-offs are disclosed here. Most trade completeness for simplicity or safety under the delivery timeline. 

- **Streaming vs non-streaming response**. Streaming is better for user experience. However, implementation for streaming is more complex and more things could go wrong. In light of a one week deadline and app requirements, a simpler non-streaming option is chosen. Replies arrive all at once after a "thinking…".

- **API and Backend service**: Since non-streaming is chosen, REST is used. Flask is chosen to reduce risk of issues. FastAPI, for example, require special care to work properly with pyinstaller packaging.

### Additional features
- File tools pose a security/safety risk where important files (eg system files) could be unintentionally overwritten or deleted. A per-agent sandbox folder is used to constrain file manipulation to within the folder.

### Backend
- Tool-calling mechanism: For native tool calling, the function signature is passed to the model separately from the prompt. For prompt-based tool calling, the function signature and agent loop instructions are included in the prompt. Native tool-calling requires fewer prompt tokens, more robust tool-calling, and less code, but not all LLMs support it. Native tool calling is chosen since robust tool-calling is important for agent applications.

- **One conversation per agent.** Each agent has a single ongoing conversation; there are no threads, titles, or a conversation switcher. Clear conversation resets it. Multiple conversations per agent is better for user experience, but is more complex to implement.

- A registry pattern is used to register each tool-call function. Each agent only has a record of the names of tools it has access to, and tool function handlers etc are retrieved at runtime. Some tools require agent-specific information like sandbox folder; this is implemented by including additional Context argument for the functions (which the LLM does not need to be aware of). All these ensures dynamic tool registration and isolation. Note that the per-agent Context can also be extended to provide tools with state or persistent memory.

- LLM provider base_url is not hardcoded - this allows easy extension to other openAI-compatible LLM providers.

- **Curated model list.** Models are constrained to a hand-picked list, since not all models are guaranteed to support native tool calling.
