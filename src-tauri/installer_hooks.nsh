; Aurora AI Econometrica — NSIS installer hooks (v1.0.9+)
;
; Цель: предотвратить Windows Defender Firewall prompt при первом запуске
; sidecar'а на ephemeral port. На корпоративных RDP-серверах нет interactive
; admin для разрешения диалога — без правил sidecar блокируется.
;
; Оба правила scoped на localip=127.0.0.1 — только loopback, никакого
; внешнего экспозиш.
;
; Phase 3.1 (2026-05-23): PREINSTALL hook убивает running sidecar + GUI
; чтобы NSIS мог перезаписать .pyd / .dll. Это safety net на случай если
; Rust-side stop_sidecar не сработал (manual installer run, watchdog respawn
; race между shutdown и installer launch). Без этого update silently
; пропускает локнутые файлы → frontend новый + sidecar старый = silent gaps.

!macro NSIS_HOOK_PREINSTALL
  ; P3.1 install-lock fix: освобождаем .pyd / .dll перед extract.
  ; taskkill /IM matches by image name (idempotent — no-op если процесс уже мёртв).
  ; /T убивает дерево, /F форсирует. ExecWait блокирует до завершения.
  ; Игнорируем exit code: 128 = "process not found" — это OK, цель достигнута.
  ;
  ; ASCII-only DetailPrint (audit 2026-05-23): Cyrillic в Tauri 2 NSIS template
  ; не verified в production-tested Aurora products. Safer fallback на English
  ; чтобы избежать garbled text на customer screen при first NSIS build.
  ;
  ; USERNAME filter (audit 2026-05-23): на multi-user RDP server taskkill /IM
  ; без USERNAME filter может убить процесс другого пользователя с похожим
  ; именем. /FI "USERNAME eq %USERNAME%" scope kill только к current installer
  ; user context (даже если elevated — installer runs as invoking user).
  DetailPrint "Preparing for update: stopping background processes..."
  ExecWait 'taskkill /IM "econometrica-sidecar.exe" /FI "USERNAME eq %USERNAME%" /T /F' $0
  Sleep 1500
  ExecWait 'taskkill /IM "aurora-econometrica-gui.exe" /FI "USERNAME eq %USERNAME%" /T /F' $0
  Sleep 1000
  ; Доп. страховка для PyInstaller-bundle процессов (multiprocessing workers).
  ; Sidecar python.exe spawned с CREATE_NO_WINDOW → WINDOWTITLE filter likely no-op
  ; в normal case, но USERNAME filter дополнительно scope'ит для RDP safety.
  ExecWait 'taskkill /IM "python.exe" /FI "USERNAME eq %USERNAME%" /FI "WINDOWTITLE eq econometrica*" /T /F' $0
  Sleep 500
!macroend

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
  ; Phase: освободить .pyd / .dll ДО удаления файлов. Без этого
  ; econometrica-sidecar.exe (или его python-воркеры) держит локи → uninstall
  ; зависает / оставляет файлы → «танцы с бубном» при установке новой версии.
  ; Тот же kill-блок, что в PREINSTALL (idempotent: exit 128 = "not found" = OK).
  ; USERNAME filter — RDP multi-user safety (не убить чужой процесс).
  DetailPrint "Stopping background processes before uninstall..."
  ExecWait 'taskkill /IM "econometrica-sidecar.exe" /FI "USERNAME eq %USERNAME%" /T /F' $0
  Sleep 1500
  ExecWait 'taskkill /IM "aurora-econometrica-gui.exe" /FI "USERNAME eq %USERNAME%" /T /F' $0
  Sleep 1000
  ExecWait 'taskkill /IM "python.exe" /FI "USERNAME eq %USERNAME%" /FI "WINDOWTITLE eq econometrica*" /T /F' $0
  Sleep 500
  ExecWait 'netsh advfirewall firewall delete rule \
name="Aurora AI Econometrica (loopback)"'
  ExecWait 'netsh advfirewall firewall delete rule \
name="Aurora AI Econometrica Sidecar (loopback)"'
!macroend
