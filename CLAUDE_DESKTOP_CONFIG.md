# Конфигурация для Claude Desktop

## ✅ Все готово к использованию!

После успешного прохождения `test_imports.py`, настройте Claude Desktop:

## 1. Откройте конфигурационный файл

```bash
nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

## 2. Добавьте конфигурацию

```json
{
  "mcpServers": {
    "project-indexer": {
      "command": "/Volumes/LaCie/mcp/project-scanner/venv/bin/python",
      "args": ["/Volumes/LaCie/mcp/project-scanner/run_server.py"],
      "env": {
        "OPENAI_API_KEY": "sk-ваш-настоящий-api-ключ-здесь"
      }
    }
  }
}
```

**Важно:**
- Используйте ПОЛНЫЕ пути (не относительные!)
- Замените `sk-ваш-настоящий-api-ключ-здесь` на ваш настоящий OpenAI API ключ

## 3. Сохраните и закройте

- Ctrl+O (сохранить)
- Enter (подтвердить)
- Ctrl+X (выход)

## 4. Перезапустите Claude Desktop

Полностью закройте и откройте заново Claude Desktop.

## 5. Проверьте что MCP сервер загружен

В чате Claude Desktop напишите:
```
Какие MCP инструменты доступны?
```

Должно появиться:
- **project-indexer** с 8 инструментами:
  - `index_project` - Полная индексация
  - `search_code` - Поиск с кодом
  - `search_files` - Поиск файлов
  - `get_project_info` - Информация о проекте
  - `list_projects` - Список проектов
  - `update_files` - Обновить файлы
  - `remove_files` - Удалить файлы
  - `delete_project_index` - Удалить проект

## 6. Первый тест

Создайте тестовый проект:

```bash
mkdir /tmp/test-project
cat > /tmp/test-project/main.py << 'EOF'
def greet(name):
    """Say hello to someone."""
    return f"Hello, {name}!"

def main():
    print(greet("World"))

if __name__ == "__main__":
    main()
EOF

cat > /tmp/test-project/README.md << 'EOF'
# Test Project

Simple Python project for testing the MCP indexer.
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
    "frameworks": [],
    "architecture_type": "cli-tool",
    "purpose": "Simple test project"
  },
  "stats": {
    "total_files": 2,
    "indexed_files": 2,
    "total_chunks": 2,
    "duration_seconds": ~15-30
  }
}
```

Затем попробуйте поиск:
```
Найди функцию для приветствия
```

Должен найти функцию `greet` с её описанием!

## Troubleshooting

### MCP сервер не загружается

1. **Проверьте логи Claude Desktop:**
   ```bash
   tail -f ~/Library/Logs/Claude/mcp*.log
   ```

2. **Проверьте что пути абсолютные:**
   - ✅ `/Volumes/LaCie/mcp/project-scanner/venv/bin/python`
   - ❌ `./venv/bin/python`

3. **Проверьте что venv использует Python 3.12:**
   ```bash
   /Volumes/LaCie/mcp/project-scanner/venv/bin/python --version
   # Должно показать: Python 3.12.x
   ```

4. **Проверьте что API ключ правильный:**
   - Не должно быть пробелов
   - Должен начинаться с `sk-`

### "ModuleNotFoundError"

Переустановите зависимости:
```bash
cd /Volumes/LaCie/mcp/project-scanner
source venv/bin/activate
pip install -r requirements.txt
```

### "Configuration error: OPENAI_API_KEY"

В конфиге Claude Desktop добавьте:
```json
"env": {
  "OPENAI_API_KEY": "sk-ваш-ключ"
}
```

### Сервер запускается но инструменты не работают

Проверьте что `.env` файл содержит правильный ключ:
```bash
cat /Volumes/LaCie/mcp/project-scanner/.env | grep OPENAI_API_KEY
```

## Альтернативная конфигурация (через bash скрипт)

Если прямой запуск не работает, используйте bash wrapper:

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

## Примеры использования в Claude Desktop

### Индексация проекта

```
Проиндексируй мой проект в ~/projects/my-app
```

### Поиск кода

```
Найди где обрабатываются HTTP запросы
```

```
Покажи функции для работы с базой данных
```

```
Найди тесты для аутентификации
```

### Информация о проекте

```
Покажи информацию об индексированном проекте ~/projects/my-app
```

### Удаление индекса

```
Удали индекс проекта ~/projects/my-app
```

## Готово!

Теперь вы можете использовать интеллектуальную индексацию и семантический поиск по вашим проектам прямо в Claude Desktop! 🚀
