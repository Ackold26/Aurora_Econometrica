; Aurora AI Econometrica — NSIS installer hooks (v1.0.9+)
;
; Цель: предотвратить Windows Defender Firewall prompt при первом запуске
; sidecar'а на ephemeral port. На корпоративных RDP-серверах нет interactive
; admin для разрешения диалога — без правил sidecar блокируется.
;
; Оба правила scoped на localip=127.0.0.1 — только loopback, никакого
; внешнего экспозиш.

!macro NSIS_HOOK_POSTINSTALL
  ; GUI exe
  ExecWait 'netsh advfirewall firewall add rule \
name="Aurora AI Econometrica (loopback)" \
dir=in action=allow protocol=TCP localip=127.0.0.1 \
program="$INSTDIR\aurora-econometrica-gui.exe"'
  ; Sidecar exe (bundled sub-dir)
  ExecWait 'netsh advfirewall firewall add rule \
name="Aurora AI Econometrica Sidecar (loopback)" \
dir=in action=allow protocol=TCP localip=127.0.0.1 \
program="$INSTDIR\sidecar\econometrica\econometrica-sidecar.exe"'
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ExecWait 'netsh advfirewall firewall delete rule \
name="Aurora AI Econometrica (loopback)"'
  ExecWait 'netsh advfirewall firewall delete rule \
name="Aurora AI Econometrica Sidecar (loopback)"'
!macroend
