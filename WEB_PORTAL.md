# 🌐 Web Admin Portal

Веб-интерфейс для управления и просмотра индексированных проектов с поддержкой трёхуровневой системы индексации (Project Analysis → File Index → Function Index).

## 🚀 Запуск

### Быстрый старт

```bash
# Запустить на порту 8080 (по умолчанию)
python run_web_server.py

# Запустить на другом порту
python run_web_server.py --port 3000

# Запустить на определенном хосте
python run_web_server.py --host 127.0.0.1 --port 8080
```

После запуска откройте в браузере:
```
http://localhost:8080
```

### 🗺️ Навигация по интерфейсу

```
Главная страница (/)
    ↓
    ├─→ Analysis (/analysis.html) ─ Index 1: Project Analysis
    ├─→ Functions (/functions.html) ─ Index 3: Function Search
    ├─→ Status Monitor (/checkpoints.html) ─ 3-Index Status
    └─→ API Docs (/docs) ─ Swagger UI
```

**Доступные URL:**
- `http://localhost:8080/` - Главная (список проектов)
- `http://localhost:8080/analysis.html` - Анализ проекта
- `http://localhost:8080/functions.html` - Поиск функций
- `http://localhost:8080/checkpoints.html` - Мониторинг статуса
- `http://localhost:8080/docs` - API документация (Swagger)
- `http://localhost:8080/redoc` - API документация (ReDoc)

## 📊 Возможности

### 🎯 Трёхуровневая система индексации
- ✅ **Index 1: Project Analysis** - Итеративный анализ проекта с confidence scores
- ✅ **Index 2: File Index** - Семантическая индексация файлов
- ✅ **Index 3: Function Index** - AST-анализ и индексация функций
- ✅ **Комбинированный статус** - Единый endpoint для мониторинга всех трёх индексов

### 📁 Управление проектами
- ✅ Просмотр всех индексированных проектов
- ✅ Статистика по каждому индексу (analysis/files/functions)
- ✅ Детальная информация о проекте
- ✅ Tech stack, frameworks, архитектура
- ✅ Дата индексации и статусы индексов
- ✅ **Удаление проекта** из индекса с подтверждением
- ✅ **Запуск анализа** проекта через UI

### 📄 Работа с файлами (Index 2)
- ✅ **Список всех файлов** проекта с пагинацией
- ✅ **Поиск по имени файла**
- ✅ **Семантический поиск** по содержимому
- ✅ **Информация о файлах:** язык, тип, назначение, количество chunks
- ✅ **Цветовое кодирование** типов файлов
- ✅ **Просмотр содержимого** - все chunks с метаданными
- ✅ **Метаданные chunks:** dependencies, exported symbols, purpose
- ✅ **Копирование кода** в буфер обмена
- ✅ **Обновление индекса** конкретных файлов

### 🔧 Работа с функциями (Index 3)
- ✅ **Список всех функций** проекта
- ✅ **Фильтрация** по языку, классу
- ✅ **Семантический поиск** функций
- ✅ **Детальная информация:** код, параметры, описание, сложность
- ✅ **Функции файла** - все функции конкретного файла
- ✅ **Переиндексация функций** через API

### 📊 Анализ проекта (Index 1)
- ✅ **Получение анализа** - tech stack, frameworks, modules, architecture
- ✅ **История итераций** - просмотр всех итераций анализа
- ✅ **Confidence scores** - уровни уверенности по каждому полю
- ✅ **Запуск анализа** - старт/resume через API

### 🎨 UI/UX
- ✅ **Темная тема** для отображения кода
- ✅ **Система уведомлений** - success/error/info toast messages
- ✅ **Syntax highlighting** для кода (опционально)
- ✅ **Responsive design** (если используется Tailwind CSS)

### REST API Endpoints

## 🔷 Базовые Endpoints

### 1. Health Check
```bash
GET /api/health
```
Проверка работоспособности сервера.

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "mcp_server": "project-indexer"
}
```

### 2. Список проектов
```bash
GET /api/projects
```
Список всех проектов с агрегированными данными из трёх индексов.

**Response:**
```json
{
  "total": 2,
  "projects": [
    {
      "project_name": "My Project",
      "project_path": "/path/to/project",
      "project_description": "E-commerce API...",
      "tech_stack": ["Python", "TypeScript"],
      "frameworks": ["FastAPI", "React"],
      "architecture_type": "microservices",
      "total_files": 150,
      "total_functions": 420,
      "indexed_at": 1738329600,
      "analysis_status": "completed",
      "files_status": "completed",
      "functions_status": "completed"
    }
  ]
}
```

### 3. Информация о проекте
```bash
GET /api/projects/{project_path}/info
```
Детальная информация о проекте из Index 1.

**Example:**
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/info"
```

**Response:**
```json
{
  "status": "indexed",
  "project_id": "project_abc123_files",
  "project_context": {
    "project_name": "My Project",
    "project_description": "...",
    "tech_stack": ["Python", "JavaScript"],
    "frameworks": ["FastAPI", "React"],
    "architecture_type": "microservices",
    "key_entry_points": ["main.py", "app.py"],
    "purpose": "E-commerce platform"
  },
  "stats": {
    "analysis": {...},
    "files": {...},
    "functions": {...}
  }
}
```

### 4. Комбинированный статус индексов
```bash
GET /api/projects/{project_path}/index-status
```
Статус всех трёх индексов с реальным количеством файлов.

**Response:**
```json
{
  "status": "success",
  "project_path": "/path/to/project",
  "indices": {
    "analysis": {
      "status": "completed",
      "iteration_count": 3,
      "min_confidence": 92,
      "files_analyzed": 15,
      "languages": ["Python", "TypeScript"],
      "frameworks": ["FastAPI", "React"]
    },
    "files": {
      "status": "completed",
      "total_files": 150,
      "indexed_files": 150,
      "completed_files": 148,
      "failed_files": 2,
      "total_chunks": 425
    },
    "functions": {
      "status": "completed",
      "total_files": 120,
      "indexed_files": 120,
      "completed_files": 118,
      "failed_files": 2,
      "total_functions": 420
    }
  }
}
```

### 5. Удалить проект
```bash
DELETE /api/projects/{project_path}
```
Удалить проект из всех индексов.

## 📁 Index 2: File Index Endpoints

### 6. Список файлов
```bash
GET /api/projects/{project_path}/files?limit=100&offset=0
```
Список файлов с пагинацией.

**Query Parameters:**
- `limit` - max results (default: 100)
- `offset` - pagination offset (default: 0)

**Response:**
```json
{
  "total": 150,
  "files": [
    {
      "relative_path": "src/main.py",
      "language": "python",
      "file_type": "code",
      "purpose": "Main entry point",
      "chunks": 3
    }
  ]
}
```

### 7. Содержимое файла
```bash
GET /api/projects/{project_path}/files/{file_path}
```
Все chunks файла с метаданными.

**Example:**
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/files/src%2Fmain.py"
```

**Response:**
```json
{
  "status": "success",
  "file_path": "src/main.py",
  "total_chunks": 2,
  "chunks": [
    {
      "chunk_index": 0,
      "total_chunks": 2,
      "content": "import os\n\ndef main():\n    ...",
      "purpose": "Main entry point",
      "dependencies": ["os", "sys"],
      "exported_symbols": ["main"],
      "language": "python",
      "file_type": "code"
    }
  ]
}
```

### 8. Семантический поиск файлов
```bash
GET /api/projects/{project_path}/search?query=authentication+logic&n_results=10&file_type=code&language=python
```
Семантический поиск по файлам (Index 2).

**Query Parameters:**
- `query` - search query (required)
- `n_results` - max results (default: 10)
- `file_type` - filter: code | documentation | config | test
- `language` - filter by language

### 9. Обновить индекс файлов
```bash
POST /api/projects/{project_path}/files/update
Content-Type: application/json

{
  "file_paths": ["src/main.py", "src/utils.py"]
}
```
Инкрементальное обновление индекса конкретных файлов.

**Response:**
```json
{
  "status": "success",
  "stats": {
    "updated_files": 2,
    "failed_files": 0,
    "total_chunks": 5
  }
}
```

## 🔧 Index 3: Function Index Endpoints

### 10. Список функций
```bash
GET /api/projects/{project_path}/functions?language=python&class_name=MyClass&limit=100&offset=0
```
Список всех функций с фильтрацией.

**Query Parameters:**
- `language` - filter by language (optional)
- `class_name` - filter by class (optional)
- `limit` - max results (default: 100)
- `offset` - pagination offset (default: 0)

**Response:**
```json
{
  "status": "success",
  "total": 420,
  "functions": [
    {
      "id": "func_abc123",
      "name": "validate_email",
      "file_path": "src/validators.py",
      "line_start": 10,
      "line_end": 25,
      "class_name": null,
      "is_method": false,
      "is_async": false,
      "language": "python",
      "description": "Validates email format",
      "complexity": "low"
    }
  ]
}
```

### 11. Семантический поиск функций
```bash
GET /api/projects/{project_path}/functions/search?q=validate+email&n_results=10&language=python
```
Поиск функций по описанию.

**Query Parameters:**
- `q` - search query (required)
- `n_results` - max results (default: 10)
- `language` - filter by language (optional)
- `class_name` - filter by class (optional)

### 12. Детали функции
```bash
GET /api/projects/{project_path}/functions/{function_id}
```
Полная информация о функции включая код.

**Response:**
```json
{
  "status": "success",
  "function": {
    "id": "func_abc123",
    "name": "validate_email",
    "file_path": "src/validators.py",
    "line_start": 10,
    "line_end": 25,
    "signature": "def validate_email(email: str) -> bool:",
    "description": "Validates email format using regex",
    "purpose": "Input validation",
    "parameters": ["email: str"],
    "return_type": "bool",
    "side_effects": [],
    "complexity": "low",
    "is_async": false,
    "code": "def validate_email(email: str) -> bool:\n    ..."
  }
}
```

### 13. Функции файла
```bash
GET /api/projects/{project_path}/files/{file_path}/functions
```
Все функции конкретного файла.

**Response:**
```json
{
  "status": "success",
  "total": 5,
  "file_path": "src/validators.py",
  "functions": [
    {
      "id": "func_abc123",
      "name": "validate_email",
      "line_start": 10,
      "line_end": 25,
      "class_name": null,
      "is_method": false,
      "is_async": false,
      "description": "Validates email",
      "purpose": "Input validation",
      "complexity": "low",
      "code": "def validate_email(...):\n    ..."
    }
  ]
}
```

### 14. Переиндексация функций
```bash
POST /api/projects/{project_path}/functions/reindex
Content-Type: application/json

{
  "force_reindex": false
}
```
Запуск переиндексации функций (Index 3).

## 📊 Index 1: Project Analysis Endpoints

### 15. Получить анализ проекта
```bash
GET /api/projects/{project_path}/analysis
```
Результат итеративного анализа проекта.

**Response:**
```json
{
  "status": "success",
  "project_path": "/path/to/project",
  "completed": true,
  "iteration_count": 3,
  "files_analyzed": ["README.md", "package.json", "src/main.py"],
  "analysis": {
    "description": "E-commerce platform API",
    "description_confidence": 95,
    "languages": ["Python", "TypeScript"],
    "languages_confidence": 98,
    "frameworks": ["FastAPI", "React"],
    "frameworks_confidence": 92,
    "modules": ["auth", "payments", "products"],
    "modules_confidence": 88,
    "entry_points": ["main.py", "app.py"],
    "entry_points_confidence": 90,
    "architecture": "microservices",
    "architecture_confidence": 85
  },
  "min_confidence": 85
}
```

### 16. История итераций
```bash
GET /api/projects/{project_path}/analysis/iterations
```
Просмотр всех итераций анализа.

**Response:**
```json
{
  "status": "success",
  "total": 3,
  "iterations": [
    {
      "iteration": 1,
      "files_requested": ["README.md", "package.json"],
      "files_read": ["README.md", "package.json"],
      "created_at": "2026-02-06T12:00:00Z"
    }
  ]
}
```

### 17. Запуск анализа проекта
```bash
POST /api/projects/{project_path}/analysis/start
Content-Type: application/json

{
  "force_reindex": false
}
```
Запуск или resume итеративного анализа.

**Response:**
```json
{
  "status": "success",
  "completed": true,
  "iteration_count": 3,
  "min_confidence": 90
}
```

## 🔧 Конфигурация

В файле `.env`:

```bash
# Web Server Configuration
WEB_HOST=0.0.0.0        # Адрес хоста
WEB_PORT=8080           # Порт
WEB_ENABLE=false        # Автозапуск (пока не реализовано)
```

## 📚 Документация API

После запуска сервера доступна автоматическая документация:

- **Swagger UI**: http://localhost:8080/docs
- **ReDoc**: http://localhost:8080/redoc
- **OpenAPI JSON**: http://localhost:8080/openapi.json

## 🌐 Веб-интерфейс (HTML страницы)

Веб-портал включает 4 специализированные страницы для управления индексами:

### 1. **Главная страница** (`/` или `/index.html`)
**URL:** `http://localhost:8080/`

**Возможности:**
- 📊 **Dashboard** - обзор всех проектов
- 📈 **Статистика** - количество проектов, файлов, функций
- 🔍 **Поиск проектов** - фильтрация по имени
- 📁 **Карточки проектов** с информацией:
  - Tech stack (Python, TypeScript, etc.)
  - Frameworks (FastAPI, React, etc.)
  - Архитектура (microservices, monolithic, etc.)
  - Статусы индексов (✅ completed / 🔄 in_progress / ⏸️ pending)
  - Количество файлов и функций
- ⚡ **Быстрые действия**:
  - Просмотр деталей проекта
  - Переход к анализу проекта
  - Переход к функциям проекта
  - Удаление проекта
- 🎨 **Навигация** - вкладки для перехода на другие страницы

### 2. **Project Analysis** (`/analysis.html`)
**URL:** `http://localhost:8080/analysis.html`

**Index 1: Итеративный анализ проекта**

**Возможности:**
- 🔍 **Выбор проекта** - ввод пути к проекту
- ▶️ **Запуск анализа** - старт/resume итеративного анализа
- 📊 **Результаты анализа** с confidence scores:
  - 📝 Description - описание проекта (с % уверенности)
  - 🔤 Languages - языки программирования (Python, TypeScript, etc.)
  - 🛠️ Frameworks - фреймворки (FastAPI, React, etc.)
  - 📦 Modules - основные модули проекта
  - 🚪 Entry Points - точки входа (main.py, index.ts, etc.)
  - 🏗️ Architecture - тип архитектуры (microservices, library, etc.)
- 🔄 **История итераций** - детальный просмотр каждой итерации:
  - Iteration number
  - Files requested & read
  - Timestamp
- 📈 **Прогресс-бар** - визуализация уверенности (минимальный confidence score)
- 🎯 **Цветовое кодирование**:
  - 🟢 90%+ - высокая уверенность (зелёный)
  - 🟡 70-89% - средняя уверенность (жёлтый)
  - 🔴 <70% - низкая уверенность (красный)

### 3. **Function Index** (`/functions.html`)
**URL:** `http://localhost:8080/functions.html`

**Index 3: Семантический поиск функций**

**Возможности:**
- 🔍 **Semantic Search** - естественный язык:
  - "Find functions that validate email"
  - "Show password hashing functions"
  - "Functions that write to database"
- 🎛️ **Фильтры**:
  - Language (Python, TypeScript, Kotlin, etc.)
  - Class name (для методов)
  - Limit (количество результатов)
- 📋 **Список функций** с информацией:
  - Function name
  - File path (relative)
  - Line numbers (start-end)
  - Class name (if method)
  - Description (AI-generated)
  - Complexity level (low/medium/high)
  - Badges: async, method, language
- 🔎 **Детальный просмотр** функции (клик на карточку):
  - Full source code
  - Function signature
  - Parameters & return type
  - Purpose & description
  - Side effects (DB writes, API calls, etc.)
  - Dependencies used
- 💾 **Copy to clipboard** - копирование кода функции
- 🎨 **Syntax highlighting** - подсветка синтаксиса кода

### 4. **3-Index Status Monitor** (`/checkpoints.html`)
**URL:** `http://localhost:8080/checkpoints.html`

**Мониторинг всех трёх индексов**

**Возможности:**
- 📊 **Unified Dashboard** - статус всех индексов в одном месте
- 🔄 **Real-time updates** - автообновление статуса
- 📈 **Index 1: Project Analysis**:
  - Status (completed/in_progress/pending)
  - Iteration count
  - Min confidence score
  - Files analyzed
  - Languages detected
  - Frameworks detected
- 📁 **Index 2: File Index**:
  - Status with progress indicator
  - Total files vs indexed files
  - Completed vs failed files
  - Total chunks created
  - Progress bar
- 🔧 **Index 3: Function Index**:
  - Status with progress indicator
  - Total source files vs indexed
  - Completed vs failed files
  - Total functions extracted
  - Progress bar
- 🎨 **Visual Status Indicators**:
  - ✅ Completed (зелёный)
  - 🔄 In Progress (синий с прогресс-баром)
  - ⏸️ Pending (серый)
  - ❌ Partial (жёлтый - есть ошибки)
- 📊 **Checkpoint Details** - детальная информация:
  - File-by-file breakdown
  - Error messages для failed files
  - Timestamps
  - Chunks/functions per file

## 🎨 Технологии

**Backend:**
- **FastAPI** - современный async веб-фреймворк
- **Uvicorn** - ASGI сервер для production
- **Трёхуровневая система:**
  - `IterativeProjectAnalyzer` - Index 1 (Project Analysis)
  - `FileIndexManager` - Index 2 (File Index)
  - `FunctionIndexManager` - Index 3 (Function Index)
- **ChromaManager** - работа с векторными индексами
- **CheckpointManager** - управление чекпоинтами
- **AnalysisRepository** - хранение результатов анализа

**Frontend:**
- **Vue.js 3** (via CDN) - реактивный UI
- **Tailwind CSS** (via CDN) - utility-first CSS фреймворк
- **Vanilla JavaScript** - для дополнительной логики
- **4 HTML страницы** - специализированные интерфейсы для каждого индекса

**API:**
- **17+ REST endpoints** с полной поддержкой 3-index системы
- **OpenAPI/Swagger** - автоматическая документация
- **CORS** - настроенный для локальной разработки

**UI/UX:**
- 🎨 **Responsive Design** - работает на всех экранах
- 🌙 **Dark theme** для кода
- ⚡ **Animations** - плавные переходы (fadeIn, pulse)
- 📊 **Progress bars** - визуализация прогресса
- 🏷️ **Badges & Tags** - цветовое кодирование статусов
- 📋 **Toast notifications** - system feedback

## 🔒 Безопасность

⚠️ **Важно:**
- Веб-портал не имеет аутентификации
- Рекомендуется использовать только в локальной сети
- Для production нужно добавить:
  - Аутентификацию (OAuth, JWT)
  - HTTPS
  - Rate limiting
  - CORS ограничения

## 🐛 Отладка

### Проверка работы сервера
```bash
curl http://localhost:8080/api/health
```

### Просмотр логов
Логи выводятся в консоль при запуске:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080
```

### Проверка доступных проектов
```bash
curl http://localhost:8080/api/projects | jq
```

## 🎯 Примеры работы с интерфейсом

### Сценарий 1: Первый запуск и индексация нового проекта

1. **Откройте главную страницу** (`http://localhost:8080/`)
   - Увидите список уже проиндексированных проектов (если есть)

2. **Перейдите на Analysis** (вкладка или `/analysis.html`)
   - Введите путь к проекту: `/Users/john/my-project`
   - Нажмите **"Start Analysis"**
   - Наблюдайте за прогрессом итеративного анализа
   - Дождитесь 90%+ confidence по всем полям

3. **Проверьте статус** на `/checkpoints.html`
   - Должны увидеть Analysis: ✅ Completed
   - Files: ⏸️ Pending
   - Functions: ⏸️ Pending

4. **Запустите индексацию файлов** (через MCP или напрямую через API)
   ```bash
   curl -X POST "http://localhost:8080/api/projects/%2Fusers%2Fjohn%2Fmy-project/files/update" \
     -H "Content-Type: application/json" \
     -d '{"file_paths": []}'  # пустой массив = все файлы
   ```

5. **Запустите индексацию функций**
   ```bash
   curl -X POST "http://localhost:8080/api/projects/%2Fusers%2Fjohn%2Fmy-project/functions/reindex"
   ```

### Сценарий 2: Поиск функции по описанию

1. **Откройте Functions** (`/functions.html`)
2. **Выберите проект** из выпадающего списка или введите путь
3. **Введите запрос** на естественном языке:
   - "Find functions that validate user input"
   - "Show password hashing functions"
   - "Functions that call external API"
4. **Примените фильтры** (опционально):
   - Language: Python
   - Limit: 20
5. **Нажмите "Search"**
6. **Кликните на функцию** для просмотра полного кода
7. **Скопируйте код** кнопкой "Copy Code"

### Сценарий 3: Мониторинг прогресса индексации

1. **Откройте Status Monitor** (`/checkpoints.html`)
2. **Введите путь к проекту**
3. **Нажмите "Load Status"**
4. **Наблюдайте за индексацией:**
   - Index 1: ✅ Completed (3 iterations, 95% confidence)
   - Index 2: 🔄 In Progress (45/150 files, 30%)
   - Index 3: ⏸️ Pending (waiting for files)
5. **Обновляйте** кнопкой "Refresh" для актуальных данных

### Сценарий 4: Обновление после изменений кода

1. **Внесли изменения** в файлы `src/api.py` и `src/models.py`
2. **Откройте главную страницу**, найдите проект
3. **Используйте API** для обновления:
   ```bash
   curl -X POST "http://localhost:8080/api/projects/YOUR_PROJECT/files/update" \
     -H "Content-Type: application/json" \
     -d '{"file_paths": ["src/api.py", "src/models.py"]}'
   ```
4. **Переиндексируйте функции** (если изменились сигнатуры):
   ```bash
   curl -X POST "http://localhost:8080/api/projects/YOUR_PROJECT/functions/reindex"
   ```
5. **Проверьте на `/checkpoints.html`** что обновление прошло успешно

## 📝 Примеры использования API

### Базовые операции

#### Проверка статуса всех индексов
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/index-status" | jq
```

#### Получить анализ проекта (Index 1)
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/analysis" | jq
```

#### Запустить анализ проекта
```bash
curl -X POST "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/analysis/start" \
  -H "Content-Type: application/json" \
  -d '{"force_reindex": false}' | jq
```

### Работа с файлами (Index 2)

#### Семантический поиск файлов
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/search?query=authentication+logic&n_results=5&file_type=code" | jq
```

#### Получить список файлов
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/files?limit=50" | jq
```

#### Получить содержимое файла
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/files/src%2Fmain.py" | jq
```

#### Обновить индекс файлов
```bash
curl -X POST "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/files/update" \
  -H "Content-Type: application/json" \
  -d '{"file_paths": ["src/api.py", "src/models.py"]}' | jq
```

### Работа с функциями (Index 3)

#### Поиск функций валидации
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/functions/search?q=validate+email&n_results=5" | jq
```

#### Получить список всех функций
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/functions?language=python&limit=100" | jq
```

#### Получить функции конкретного файла
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/files/src%2Fvalidators.py/functions" | jq
```

#### Детали конкретной функции
```bash
curl "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/functions/func_abc123" | jq
```

#### Переиндексировать функции
```bash
curl -X POST "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject/functions/reindex" \
  -H "Content-Type: application/json" \
  -d '{"force_reindex": false}' | jq
```

### Управление проектами

#### Список всех проектов
```bash
curl "http://localhost:8080/api/projects" | jq
```

#### Удалить проект
```bash
curl -X DELETE "http://localhost:8080/api/projects/%2Fpath%2Fto%2Fproject" | jq
```

## 🚀 Развитие

### ✅ Реализовано
- [x] Инкрементальная индексация через API (`/files/update`, `/functions/reindex`)
- [x] Темная тема (для отображения кода)
- [x] Удаление проектов через API
- [x] Система уведомлений (toast messages)
- [x] История итераций анализа (`/analysis/iterations`)
- [x] Детальная статистика по индексам (`/index-status`)
- [x] Фильтрация и пагинация

### 📋 Планируется
- [ ] **Аутентификация и авторизация** (OAuth, JWT)
- [ ] **Веб-UI для управления:**
  - Запуск индексации через UI
  - Мониторинг прогресса в реальном времени
  - Визуальный просмотр call graph (если включен)
- [ ] **Графики и визуализация:**
  - Диаграммы распределения языков/frameworks
  - Timeline индексации
  - Графы зависимостей
- [ ] **Экспорт данных:**
  - Экспорт результатов поиска (JSON, CSV)
  - Экспорт анализа проекта
  - Генерация отчётов
- [ ] **WebSocket** для real-time обновлений прогресса
- [ ] **Сравнение проектов** side-by-side
- [ ] **Версионирование** - отслеживание изменений кода
- [ ] **Advanced search:**
  - Полнотекстовый поиск (не только semantic)
  - Regex поиск
  - Фильтры по датам, авторам (через git)
- [ ] **Code navigation:**
  - Jump to definition
  - Find usages
  - Dependency graph visualization

## 📐 Структура UI компонентов

### Общие элементы (все страницы)

**Header:**
- 📚 Логотип и название проекта
- 🟢 Индикатор статуса сервера
- 🔗 Кнопка "Back to Projects" (на подстраницах)

**Navigation:**
- Вкладки для переключения между страницами
- Активная вкладка выделена цветом

**Цветовая схема:**
- 🟢 Зелёный - успешно, completed
- 🔵 Синий - в процессе, in_progress
- ⚪ Серый - ожидание, pending
- 🟡 Жёлтый - частично, partial (есть ошибки)
- 🔴 Красный - ошибка, failed

### Карточки проектов (index.html)

```
┌────────────────────────────────────────┐
│ 📚 Project Name                        │
│ /absolute/path/to/project              │
│                                        │
│ 📝 Project description here...         │
│                                        │
│ Tech: [Python] [TypeScript]            │
│ Frameworks: [FastAPI] [React]          │
│ Architecture: microservices            │
│                                        │
│ 📊 150 files | 420 functions           │
│                                        │
│ Analysis: ✅ | Files: ✅ | Funcs: ✅    │
│                                        │
│ [View Details] [Analysis] [Functions]  │
│                           [🗑️ Delete]  │
└────────────────────────────────────────┘
```

### Карточки функций (functions.html)

```
┌────────────────────────────────────────┐
│ def validate_email(email: str) -> bool │
│ src/validators.py:45-60                │
│                                        │
│ Description: Validates email format    │
│ using regex pattern...                 │
│                                        │
│ [async] [method] [Python] [low]        │
│                                        │
│ [View Code] [Copy]                     │
└────────────────────────────────────────┘
```

### Модальное окно (функция детально)

```
┌────────────────────────────────────────┐
│ ✕                                      │
│ Function: validate_email               │
│ File: src/validators.py                │
│                                        │
│ Signature:                             │
│ def validate_email(email: str) -> bool │
│                                        │
│ Purpose: Input validation              │
│ Complexity: low                        │
│                                        │
│ Parameters:                            │
│ • email: str - Email address to check │
│                                        │
│ Side Effects: None                     │
│                                        │
│ Source Code:                           │
│ ┌────────────────────────────────────┐ │
│ │ def validate_email(email: str):    │ │
│ │     pattern = r'^[\w\.-]+@...'    │ │
│ │     return bool(re.match(...))     │ │
│ └────────────────────────────────────┘ │
│                                        │
│              [Copy Code]               │
└────────────────────────────────────────┘
```

### Прогресс-бары (checkpoints.html)

```
Index 2: File Index                     🔄 In Progress
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 45/150 (30%)
✅ Completed: 43 | ❌ Failed: 2 | Chunks: 128
```

## 🎨 Кастомизация UI

### Изменение цветов

Все страницы используют Tailwind CSS. Для изменения цветовой схемы:

```html
<!-- В <head> любой страницы -->
<script>
  tailwind.config = {
    theme: {
      extend: {
        colors: {
          primary: '#your-color',
          // ...
        }
      }
    }
  }
</script>
```

### Добавление новых страниц

1. Создайте HTML в `src/web/static/your-page.html`
2. Используйте шаблон существующих страниц
3. Подключите Vue.js и Tailwind через CDN
4. Добавьте роут в `src/web/server.py` (опционально)

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи сервера (выводятся в консоль)
2. Убедитесь что ChromaDB инициализирован (проверьте `CHROMA_PERSIST_DIRECTORY`)
3. Проверьте что порт 8080 не занят: `lsof -i :8080`
4. Проверьте файрвол и сетевые настройки
5. Проверьте `.env` конфигурацию (API ключи, провайдеры)
6. Просмотрите документацию API: http://localhost:8080/docs

## 📚 Дополнительная документация

- **[README.md](README.md)** - Основная документация проекта
- **[API_REFERENCE.md](API_REFERENCE.md)** - Полное описание MCP инструментов
- **Swagger UI**: http://localhost:8080/docs - Интерактивная документация API
- **ReDoc**: http://localhost:8080/redoc - Альтернативная документация

---

**Версия:** 2.0.0 | **Дата:** 2026-02-06 | **API Endpoints:** 17+ | **Система:** 3-Level Indexing
