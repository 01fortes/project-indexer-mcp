# Быстрый старт

## 1. Установка зависимостей

```bash
cd /Volumes/LaCie/mcp/project-scanner

# Создать виртуальное окружение
python3 -m venv venv

# Активировать
source venv/bin/activate

# Установить зависимости
pip install mcp chromadb openai python-dotenv pathspec aiofiles tiktoken pyyaml pydantic
```

## 2. Настройка

```bash
# Отредактировать .env и добавить настоящий OpenAI API ключ
nano .env

# Изменить OPENAI_API_KEY=sk-placeholder-replace-with-real-key
# На ваш настоящий ключ
```

## 3. Тест импортов

```bash
python3 -c "from src.config import load_config; print('OK')"
python3 -c "from src.storage.models import ProjectContext; print('OK')"
python3 -c "from src.server import main; print('OK')"
```

## 4. Запуск сервера (тест)

```bash
# Попробовать запустить сервер
python3 -m src.server
```

Сервер должен запуститься и ждать MCP команд через stdio.

## 5. Подключение к Claude Desktop

1. Откройте конфигурацию Claude Desktop:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

2. Добавьте:
```json
{
  "mcpServers": {
    "project-indexer": {
      "command": "python3",
      "args": ["-m", "src.server"],
      "env": {
        "OPENAI_API_KEY": "sk-ваш-ключ"
      },
      "cwd": "/Volumes/LaCie/mcp/project-scanner"
    }
  }
}
```

3. Перезапустите Claude Desktop

4. В чате попробуйте:
```
Проиндексируй тестовый проект в /path/to/small/test/project
```

## 6. Первый тест

Создайте маленький тестовый проект:

```bash
mkdir /tmp/test-project
cd /tmp/test-project

# Создать простой Python файл
cat > main.py << 'EOF'
def hello():
    """Say hello."""
    print("Hello, World!")

if __name__ == "__main__":
    hello()
EOF

cat > README.md << 'EOF'
# Test Project
Simple test project for indexing.
EOF
```

Затем в Claude Desktop:
```
Проиндексируй проект /tmp/test-project
```

## Troubleshooting

### ModuleNotFoundError

```bash
# Убедитесь что venv активирован
source venv/bin/activate

# Переустановите зависимости
pip install -r requirements.txt  # если будет создан
# или
pip install mcp chromadb openai python-dotenv pathspec aiofiles tiktoken pyyaml pydantic
```

### OpenAI API ошибки

Проверьте что `.env` содержит правильный API ключ:
```bash
cat .env | grep OPENAI_API_KEY
```

### ChromaDB ошибки

```bash
# Удалить данные и начать заново
rm -rf ./chroma_data
```

## Что дальше?

Смотрите [README.md](README.md) для полной документации.
