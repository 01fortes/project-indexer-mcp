# 🚀 Быстрая установка и запуск

## Проблема которую вы видите

```
ModuleNotFoundError: No module named 'src'
```

Это происходит потому что Python не может найти модуль `src`. Есть простое решение!

## ✅ Решение (5 шагов)

### 1. Установить Python 3.12 (если у вас 3.14)

```bash
brew install python@3.12
```

### 2. Создать виртуальное окружение

```bash
cd /Volumes/LaCie/mcp/project-scanner

# Используем Python 3.12 (не 3.14!)
/opt/homebrew/bin/python3.12 -m venv venv

# Активировать
source venv/bin/activate
```

### 3. Установить зависимости

```bash
pip install -r requirements.txt
```

Это установит:
- mcp (MCP SDK)
- chromadb-client (легковесная версия без ML)
- openai
- и другие зависимости

### 4. Настроить OpenAI API ключ

```bash
nano .env
```

Изменить:
```bash
OPENAI_API_KEY=sk-ваш-настоящий-ключ-здесь
```

Сохранить (Ctrl+O, Enter, Ctrl+X).

### 5. Настроить Claude Desktop

Открыть конфиг:
```bash
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Добавить:
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

**Важно:** Используйте АБСОЛЮТНЫЙ путь к `start_server.sh`!

## 🎉 Готово! Перезапустить Claude Desktop

Теперь в Claude Desktop можно использовать:

```
Проиндексируй проект /path/to/my/project
```

```
Найди код для обработки HTTP запросов
```

## Проверка что все работает

### Тест 1: Зависимости установлены

```bash
source venv/bin/activate
python -c "import mcp, openai, chromadb; print('✅ Все зависимости установлены')"
```

### Тест 2: Сервер запускается

```bash
./start_server.sh
```

Должно вывести:
```
Starting project-indexer v1.0.0
```

Нажать Ctrl+C для остановки.

### Тест 3: Claude Desktop видит сервер

1. Перезапустить Claude Desktop
2. В чате написать: "Какие MCP инструменты доступны?"
3. Должен появиться `project-indexer` с 4 инструментами

## Быстрый тест индексации

```bash
# Создать тестовый проект
mkdir /tmp/test-project
cat > /tmp/test-project/main.py << 'EOF'
def hello(name):
    """Greet someone."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(hello("World"))
EOF

cat > /tmp/test-project/README.md << 'EOF'
# Test Project
Simple test project for indexing demo.
EOF
```

В Claude Desktop:
```
Проиндексируй проект /tmp/test-project
```

Ожидаемый результат:
```json
{
  "status": "success",
  "project_context": {
    "project_name": "test-project",
    "tech_stack": ["Python"],
    ...
  },
  "stats": {
    "total_files": 2,
    "indexed_files": 2,
    "duration_seconds": ~15-30
  }
}
```

Затем:
```
Найди функцию для приветствия
```

Должен найти функцию `hello` с описанием!

## Troubleshooting

### "command not found: python3.12"

```bash
brew install python@3.12
```

### "No such file or directory: start_server.sh"

Проверьте абсолютный путь:
```bash
ls -la /Volumes/LaCie/mcp/project-scanner/start_server.sh
```

### "ModuleNotFoundError: No module named 'chromadb'"

```bash
source venv/bin/activate
pip install chromadb-client
```

### Claude Desktop не запускает сервер

Проверьте логи:
```bash
tail -f ~/Library/Logs/Claude/mcp*.log
```

Проверьте что в конфиге используется ПОЛНЫЙ путь к скрипту:
```
/Volumes/LaCie/mcp/project-scanner/start_server.sh
```

А НЕ относительный:
```
./start_server.sh  ❌ Не работает
```

### "Error: Virtual environment not found"

```bash
cd /Volumes/LaCie/mcp/project-scanner
/opt/homebrew/bin/python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Альтернативный способ запуска

Если `start_server.sh` не работает, используйте прямую команду в конфиге Claude:

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

## Нужна помощь?

1. Проверьте [INSTALL.md](INSTALL.md) для детальных инструкций
2. Проверьте [README.md](README.md) для полной документации
3. Проверьте [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) для технических деталей
