# Инструкция по установке

## Проблема с Python 3.14

Если у вас Python 3.14, ChromaDB может иметь проблемы совместимости. Рекомендуется использовать Python 3.11 или 3.12.

## Вариант 1: Простой запуск без установки пакета (РЕКОМЕНДУЕТСЯ)

### 1. Установить Python 3.11 или 3.12

```bash
# Через Homebrew
brew install python@3.12
```

### 2. Создать виртуальное окружение

```bash
cd /Volumes/LaCie/mcp/project-scanner

# Используем Python 3.12
/opt/homebrew/bin/python3.12 -m venv venv

# Активировать
source venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

### 4. Настроить .env

```bash
nano .env
# Изменить OPENAI_API_KEY на настоящий ключ
```

### 5. Запустить сервер

```bash
# Вариант 1: Через launcher скрипт
python run_server.py

# Вариант 2: Напрямую
python -c "import sys; sys.path.insert(0, 'src'); from server import main; main()"
```

## Вариант 2: Установка пакета (если нужно)

```bash
# После активации venv
pip install -e .
python -m src.server
```

## Конфигурация для Claude Desktop

В `~/Library/Application Support/Claude/claude_desktop_config.json`:

### Вариант 1: С launcher скриптом

```json
{
  "mcpServers": {
    "project-indexer": {
      "command": "/Volumes/LaCie/mcp/project-scanner/venv/bin/python",
      "args": ["/Volumes/LaCie/mcp/project-scanner/run_server.py"],
      "env": {
        "OPENAI_API_KEY": "sk-ваш-ключ"
      }
    }
  }
}
```

### Вариант 2: С bash wrapper

Создайте файл `start_server.sh`:

```bash
#!/bin/bash
cd /Volumes/LaCie/mcp/project-scanner
source venv/bin/activate
exec python run_server.py
```

```bash
chmod +x start_server.sh
```

Затем в config:

```json
{
  "mcpServers": {
    "project-indexer": {
      "command": "/Volumes/LaCie/mcp/project-scanner/start_server.sh",
      "env": {
        "OPENAI_API_KEY": "sk-ваш-ключ"
      }
    }
  }
}
```

## Тестирование

### 1. Проверить что зависимости установлены

```bash
source venv/bin/activate
python -c "import mcp, openai, chromadb; print('OK')"
```

### 2. Проверить что сервер запускается

```bash
python run_server.py
# Должно вывести: "Starting project-indexer v1.0.0"
# Затем ждать команд через stdin
```

Нажмите Ctrl+C для остановки.

### 3. Протестировать через Claude Desktop

1. Перезапустите Claude Desktop
2. В чате напишите:
   ```
   Покажи доступные MCP инструменты
   ```

Должен появиться "project-indexer" с инструментами:
- index_project
- search_code
- get_project_info
- delete_project_index

## Troubleshooting

### Ошибка: ModuleNotFoundError: No module named 'chromadb'

```bash
source venv/bin/activate
pip install chromadb-client
```

### Ошибка: ModuleNotFoundError: No module named 'src'

Используйте `run_server.py` скрипт:
```bash
python run_server.py
```

### Ошибка: onnxruntime не совместим с Python 3.14

Используйте Python 3.12:
```bash
brew install python@3.12
/opt/homebrew/bin/python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Claude Desktop не видит сервер

1. Проверьте путь к python в конфиге
2. Проверьте что .env содержит правильный API ключ
3. Проверьте логи Claude Desktop:
   ```bash
   tail -f ~/Library/Logs/Claude/mcp*.log
   ```

## Быстрый тест

Создайте тестовый проект:

```bash
mkdir /tmp/test-project
echo "def hello(): print('Hi')" > /tmp/test-project/main.py
echo "# Test" > /tmp/test-project/README.md
```

В Claude Desktop:
```
Проиндексируй проект /tmp/test-project
```

Должен вернуть успешный результат с проанализированным контекстом.
