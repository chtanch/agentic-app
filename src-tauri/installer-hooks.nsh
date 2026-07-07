; Custom NSIS installer hooks for the Agentic Desktop bundle.
;
; Why this exists: the Python sidecar stores all app state under
; %APPDATA%\agentic-app\ (see sidecar/src/agent_backend/config.py, APP_NAME),
; which is a hardcoded name unrelated to the Tauri bundle identifier
; (com.agenticapp.desktop). Tauri's stock uninstaller only removes
; $APPDATA\${BUNDLEID} and $LOCALAPPDATA\${BUNDLEID} when the user ticks
; "delete the application data", so our real data dir was never removed.
;
; This post-uninstall hook deletes the actual data dir under the same
; conditions Tauri uses for its own cleanup: the checkbox is ticked and we
; are not in update mode. $DeleteAppDataCheckboxState and $UpdateMode are
; declared by the generated Tauri uninstaller script that inserts this macro.

!macro NSIS_HOOK_POSTUNINSTALL
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
    SetShellVarContext current
    RmDir /r "$APPDATA\agentic-app"
  ${EndIf}
!macroend
