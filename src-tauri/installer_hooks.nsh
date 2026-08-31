; Aurora AI Econometrica – NSIS installer hooks (v1.0.9+)
;
; Цель: освободить файлы движка перед установкой и удалением (kill-блоки ниже).
;
; Правила брандмауэра убраны (CPD-116, 2026-08-17). Раньше хуки заводили при
; установке и снимали при удалении два разрешающих правила на петлевой адрес
; (localip=127.0.0.1) для интерфейса и движка. Соседняя линия доказала зондом:
; петлевой трафик Windows брандмауэром НЕ фильтрует – правила ничего не
; разрешали, при этом были единственной причиной, по которой установщику
; Эконометрики требовались права администратора. Удалены и правила добавления,
; и правила снятия: иначе деинсталлятор чистил бы несуществующее.
;
; Phase 3.1 (2026-05-23): PREINSTALL hook убивает running sidecar + GUI
; чтобы NSIS мог перезаписать .pyd / .dll. Это safety net на случай если
; Rust-side stop_sidecar не сработал (manual installer run, watchdog respawn
; race между shutdown и installer launch). Без этого update silently
; пропускает локнутые файлы → frontend новый + sidecar старый = silent gaps.
;
; rc10 (2026-06-07) + фикс кодировки (2026-07-07): ВСЕ внешние команды через
; nsExec::Exec – НЕ ExecWait и НЕ ExecToLog. ExecWait для консольных программ
; (taskkill) открывает видимое чёрное окно cmd. ExecToLog запускает скрыто,
; но ТАЩИТ локализованный вывод утилит (OEM/CP866) в installer-лог → кракозябры
; на русской Windows (репорт Антона со скрином 2026-07-07). nsExec::Exec запускает
; СКРЫТО (без окна) и НЕ пишет вывод в лог; прогресс даём своим ASCII DetailPrint.
; Каждый вызов оставляет exit code на стеке → обязателен Pop $0.
;
; Сужение глушения (2026-08-10): убрана строка `taskkill /IM "python.exe"
; /FI "WINDOWTITLE eq econometrica*"` из PREINSTALL и PREUNINSTALL. Причины:
; (1) WINDOWTITLE-фильтр никогда не совпадал – python-fallback sidecar (см.
; econ_sidecar.rs::spawn_python_dev) стартует с CREATE_NO_WINDOW, у такого
; процесса нет заголовка окна, строка была мёртвым кодом с нулевой пользой;
; (2) глушение по обобщённому имени образа python.exe – известный сигнал
; эвристики антивирусов, и при ложном срабатывании фильтра рискует убить
; чужой python пользователя, а не наш sidecar. Штатный случай (закрытие
; приложения) уже закрыт из самого приложения: econ_sidecar::stop_sidecar()
; убивает движок по PID, полученному от Child-хендла, независимо от того,
; был ли он заспавнен как bundled exe или как python-fallback – см. lib.rs
; on_window_event. Остаточный риск – только если приложение упало ДО
; graceful shutdown и потом сразу запущен установщик поверх ещё живого
; python-fallback: тогда NSIS может не перезаписать locked-файл и явно
; сообщит об ошибке (не тихая порча). Точечная альтернатива – читать PID
; из `%LOCALAPPDATA%\com.aurora.econometrica\sidecar.json` (поле "pid",
; см. sidecar_runtime.rs::SidecarState) и killать `taskkill /PID <pid>`
; – не реализована здесь: требует NSIS-парсинга JSON, который в этой сессии
; негде было собрать и проверить сборкой инсталлятора.

!macro NSIS_HOOK_PREINSTALL
  ; P3.1 install-lock fix: освобождаем .pyd / .dll перед extract.
  ; taskkill /IM matches by image name (idempotent – no-op если процесс уже мёртв).
  ; /T убивает дерево, /F форсирует. Игнорируем exit code: 128 = "process not
  ; found" – это OK, цель достигнута.
  ;
  ; ASCII-only DetailPrint (audit 2026-05-23): Cyrillic в Tauri 2 NSIS template
  ; не verified в production-tested Aurora products. Safer fallback на English.
  ;
  ; USERNAME filter (audit 2026-05-23): на multi-user RDP server taskkill /IM
  ; без USERNAME filter может убить процесс другого пользователя с похожим
  ; именем. /FI "USERNAME eq %USERNAME%" scope kill только к current installer
  ; user context (даже если elevated – installer runs as invoking user).
  DetailPrint "Preparing for update: stopping background processes..."
  nsExec::Exec 'taskkill /IM "econometrica-sidecar.exe" /FI "USERNAME eq %USERNAME%" /T /F'
  Pop $0
  Sleep 1500
  nsExec::Exec 'taskkill /IM "aurora-econometrica-gui.exe" /FI "USERNAME eq %USERNAME%" /T /F'
  Pop $0
  Sleep 1000
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; Явное окно успеха установки (распоряжение Антона 2026-07-02). В silent/passive
  ; режиме подавляется (IfSilent) – там app сам перезапустится по /R (onInstSuccess).
  IfSilent +2
  MessageBox MB_ICONINFORMATION|MB_OK "Optimizer MMM успешно установлена."
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  ; Phase: освободить .pyd / .dll ДО удаления файлов. Без этого
  ; econometrica-sidecar.exe (или его python-воркеры) держит локи → uninstall
  ; зависает / оставляет файлы → «танцы с бубном» при установке новой версии.
  ; Тот же kill-блок, что в PREINSTALL (idempotent: exit 128 = "not found" = OK).
  ; USERNAME filter – RDP multi-user safety (не убить чужой процесс).
  DetailPrint "Stopping background processes before uninstall..."
  nsExec::Exec 'taskkill /IM "econometrica-sidecar.exe" /FI "USERNAME eq %USERNAME%" /T /F'
  Pop $0
  Sleep 1500
  nsExec::Exec 'taskkill /IM "aurora-econometrica-gui.exe" /FI "USERNAME eq %USERNAME%" /T /F'
  Pop $0
  Sleep 1000
!macroend
