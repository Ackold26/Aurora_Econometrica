# Системные требования — Aurora AI Econometrica

Документ описывает минимальные и рекомендуемые требования для работы приложения Aurora AI Econometrica, а также тонкости настройки среды для ускорения MCMC-обучения.

> ⚙️ Черновик. В будущем станет разделом «Установка и настройка» в полной пользовательской инструкции.

---

## 1. Операционная система

| Параметр | Минимум | Рекомендовано |
|---|---|---|
| ОС | Windows 10 (build 1903+) | Windows 11 22H2+ |
| Архитектура | x64 | x64 |
| WebView2 Runtime | Встроен в Win10 1903+ | Встроен |
| .NET | — | — (не требуется) |

> macOS и Linux пока не поддерживаются. Сборки для них возможны технически (Tauri v2 кросс-платформенный), но валидированы только на Windows.

---

## 2. Железо

### 2.1 Минимум (модель запустится, но будет медленно)

| Компонент | Требование |
|---|---|
| CPU | 4 ядра, 2.5 ГГц (Intel Core i5-8xxx / AMD Ryzen 5 2xxx) |
| RAM | 8 ГБ |
| Диск | 1.5 ГБ свободно (приложение) + 2 ГБ (рабочие проекты) |
| GPU | Не требуется |

**На минимуме:** обучение модели MCMC 2 chains × 500 draws × 500 tune на 6 медиа-каналах занимает **15-25 минут**.

### 2.2 Рекомендовано (комфортная скорость)

| Компонент | Требование |
|---|---|
| CPU | 6+ ядер, 3.5+ ГГц (Intel Core i7-12xxx / AMD Ryzen 7 5xxx+) |
| RAM | 16 ГБ |
| Диск | SSD, 5+ ГБ свободно |
| GPU | Не используется (планируется в Q3-Q4, см. §5) |

**На рекомендуемом:** обучение модели MCMC 2 × 500 × 500 на 6 каналах занимает **3-7 минут** (при установленном MSVC — см. §3).

### 2.3 Production-режим (для аналитика-консультанта)

| Компонент | Требование |
|---|---|
| CPU | 8+ ядер высокочастотный (Intel i9 / AMD Ryzen 9) |
| RAM | 32 ГБ |
| Диск | NVMe SSD, 20+ ГБ |

Позволяет параллельные прогоны Chains=4, Draws=2000 (~15 минут для публикационного качества).

---

## 3. Обязательное ПО

> ⚠️ **Обновлено 2026-04-19 на основе live-теста:** MSVC Build Tools на Windows **НЕ ускоряет PyTensor** (он требует g++, не cl.exe). Правильный путь — JAX/NumPyro backend.

### 3.1 Для всех пользователей — JAX / NumPyro (критично для скорости)

**JAX + NumPyro** — обязательные Python-пакеты для приемлемой скорости MCMC.

Без них PyMC падает на Python-fallback NUTS — sampling занимает **15-30+ минут** на типовых данных (31×34). С JAX — **секунды**.

**Установка (разово):**

```bash
pip install "jax==0.7.2" "jaxlib==0.7.2" "numpyro==0.20.1"
```

> ⚠️ **Версионный mismatch:** последний JAX (0.10+) НЕ совместим с NumPyro 0.20.1.
> Пинить строго: `jax==0.7.2`, `jaxlib==0.7.2`, `numpyro==0.20.1`.

**Проверка:**
```bash
python -c "import jax, numpyro; print('JAX:', jax.__version__); print('NumPyro:', numpyro.__version__)"
```

### 3.2 MSVC Build Tools — опционально (для Cython/NumPy)

MSVC Build Tools полезны для:
- Установки пакетов с native-extension (некоторые версии lxml, pycurl и т.д.)
- Сборки NumPy/SciPy из исходников (обычно не нужно — есть wheels)
- **НЕ помогают** PyMC/PyTensor

Если не нужно — **пропустить, поставить только JAX/NumPyro** (см. 3.1).

**Если всё же устанавливать:**

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools
```

После открытия Visual Studio Installer отметить:
- ✅ **MSVC v143 - VS 2022 C++ x64/x86 build tools**
- ✅ **Windows 11 SDK** (или Windows 10 SDK)

**Размер:** ~3.5 ГБ минимум.

**Проверка через vswhere** (работает в любом терминале):
```powershell
"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -property installationPath
```

### 3.3 Установлено автоматически инсталлятором Aurora

- WebView2 Runtime (если не установлен)
- Python runtime с PyMC, NumPy, Pandas, SciPy, **JAX, JAXlib, NumPyro** (bundled в sidecar)
- Visual C++ Redistributable 2015-2022 (стандартная зависимость)

---

## 4. Тонкости настройки

### 4.1 Проверка, что NUTS через JAX активен

В логе sidecar (`%APPDATA%\aurora-econometrica-gui\logs\sidecar-YYYY-MM-DD.log`) должна быть строка:
```
[INFO] engines.modeler: Using NumPyro NUTS sampler (JAX backend)
```

Если вместо неё:
```
[WARNING] engines.modeler: NumPyro/JAX not available — falling back to PyTensor NUTS
```
→ JAX/NumPyro не установлен (см. 3.1).

**Прямая проверка версий:**
```bash
python -c "import jax, numpyro; print(jax.__version__, numpyro.__version__)"
# Должно: 0.7.2 0.20.1
```

### 4.2 Проверка скорости обучения

На тест-данных 31×34, 6 каналов, Chains=2, Draws=500, Tune=500:
- **JAX/NumPyro:** ~5-15 секунд
- **PyTensor Python fallback:** 15-30+ минут

Если тренировка идёт дольше 30 секунд — проверить JAX.

### 4.3 Антивирус

Некоторые антивирусы (особенно Kaspersky, Dr.Web) блокируют быстрые записи кэша PyTensor в `%TEMP%\pytensor\` — это замедляет первый запуск модели в 2-3 раза.

**Рекомендация:** добавить исключения:
- `%LOCALAPPDATA%\com.aurora.econometrica\` (vault + projects)
- `%TEMP%\pytensor\` (кэш PyTensor)
- `%APPDATA%\aurora-econometrica-gui\` (проекты)

### 4.4 PowerShell execution policy

Если при первом запуске ставится блок от PowerShell:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 4.5 Russian paths / Cyrillic в пути

PyTensor исторически плохо дружит с кириллицей в пути. **Не размещать** установку в `C:\Users\<русское_имя>\...`.

**Обходной путь:** установить в `C:\Aurora\` или `D:\Программы\Aurora\` (первая папка с латиницей допустима, финальная — любая).

### 4.6 Файрвол

Приложение работает **полностью локально**, исходящих соединений нет кроме:
- GitHub Pages (`ackold26.github.io`) — проверка обновлений
- Supabase — online-авторизация лицензии

Не требуется открывать порты во внешнюю сеть.

---

## 5. Roadmap расширенных требований

### 5.1 JAX / GPU (планируется Q3-Q4)

Переключение PyMC на JAX-backend с NumPyro-sampler даст:
- Ускорение **5-10×** против NUTS на CPU
- Работу без C-компилятора

Требования при реализации:
- CUDA Toolkit 12.0+
- cuDNN 8.9+
- NVIDIA GPU с compute capability ≥ 7.0 (RTX 20xx+)
- Драйверы NVIDIA 530+

### 5.2 Облачный режим (планируется 2027)

Вычисления на серверной инфраструктуре Aurora:
- Клиентская часть — любой браузер
- Серверная часть — Kubernetes cluster с GPU-нодами
- Данные остаются локально, на сервер уходят только агрегаты (anonymized)

---

## 6. Диагностика проблем

### Модель обучается очень долго (>30 секунд на 500 draws)

**Причина 99%:** не установлены JAX / NumPyro → PyTensor Python fallback (15-30+ мин).
**Решение:** `pip install "jax==0.7.2" "jaxlib==0.7.2" "numpyro==0.20.1"` + перезапуск sidecar. См. §3.1.

### Ошибка «PyMC not found» при запуске модели

**Причина:** sidecar не смог стартовать.
**Решение:** проверить логи в `%APPDATA%\aurora-econometrica-gui\logs\` или переустановить.

### Ошибка «No module named 'pytensor'» после обновления Windows

**Причина:** обновление Windows сломало Python-кэш sidecar.
**Решение:** удалить `%TEMP%\pytensor\`, перезапустить приложение.

### R-hat > 1.1 при любых настройках

**Причина:** либо мало данных (<20 точек), либо сильная мультиколлинеарность.
**Решение:** на малых данных — дождаться OLS-режима (см. roadmap) или использовать лифт-тесты как priors. При мультиколлинеарности — проверить VIF в Expert-режиме валидации.

---

## 7. Контакты

Тех. поддержка Aurora AI: [TBD]
Документация разработчика: `README.md` в корне репозитория
