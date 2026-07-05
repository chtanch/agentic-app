"""agent_backend — Python Flask sidecar for the Windows Agentic Desktop App.

All agent/tool-calling logic lives here (PRD §5.0). The Tauri shell only
spawns and manages this process; the frontend talks to it over local REST
(Appendix A §A.2), bound to 127.0.0.1 only.
"""

__version__ = "0.1.0"
