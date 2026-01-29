# ⚠️ Важно: Используйте Python 3.12, а НЕ 3.14!

## Проблема

ChromaDB не совместим с Python 3.14. Вы получите ошибку:
```
unable to infer type for attribute "chroma_server_nofile"
```

## Решение: Установить Python 3.12

### 1. Установить Python 3.12

```bash
brew install python@3.12
```

### 2. Удалить старый venv

```bash
cd /Volumes/LaCie/mcp/project-scanner
rm -rf venv
```

### 3. Создать новый venv с Python 3.12

```bash
/opt/homebrew/bin/python3.12 -m venv venv
```

### 4. Активировать и установить зависимости

```bash
source venv/bin/activate

# Проверить версию Python
python --version
# Должно показать: Python 3.12.x

# Установить зависимости
pip install -r requirements.txt
```

### 5. Настроить .env

```bash
nano .env
# Изменить OPENAI_API_KEY на настоящий ключ
```

### 6. Протестировать

```bash
python test_imports.py
```

Должно вывести:
```
✅ All imports successful!
✅ Configuration is valid!
```

### 7. Обновить Claude Desktop конфигурацию

Используйте ПОЛНЫЙ путь к Python 3.12 venv:

```json
{
  "mcpServers": {
    "project-indexer": {
      "command": "/Volumes/LaCie/mcp/project-scanner/venv/bin/python",
      "args": ["/Volumes/LaCie/mcp/project-scanner/run_server.py"],
      "env": {
        "OPENAI_API_KEY": "sk-ваш-ключ-здесь"
      }
    }
  }
}
```

### 8. Перезапустить Claude Desktop

## Быстрая проверка версии Python

```bash
cd /Volumes/LaCie/mcp/project-scanner
source venv/bin/activate
python --version
```

Если показывает Python 3.14 - УДАЛИТЕ venv и создайте заново с 3.12!

## Полный скрипт установки

```bash
#!/bin/bash
cd /Volumes/LaCie/mcp/project-scanner

# Установить Python 3.12 если нет
if ! command -v /opt/homebrew/bin/python3.12 &> /dev/null; then
    echo "Installing Python 3.12..."
    brew install python@3.12
fi

# Удалить старый venv если есть
if [ -d "venv" ]; then
    echo "Removing old venv..."
    rm -rf venv
fi

# Создать новый venv с Python 3.12
echo "Creating venv with Python 3.12..."
/opt/homebrew/bin/python3.12 -m venv venv

# Активировать
source venv/bin/activate

# Проверить версию
echo "Python version:"
python --version

# Установить зависимости
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your OPENAI_API_KEY"
echo "2. Run: python test_imports.py"
echo "3. Configure Claude Desktop (see SETUP_PYTHON312.md)"
```

Сохраните как `setup.sh` и запустите:
```bash
chmod +x setup.sh
./setup.sh
```

## Troubleshooting

### "python3.12: command not found"

```bash
brew install python@3.12
```

### "ModuleNotFoundError" после установки

Убедитесь что venv активирован:
```bash
source venv/bin/activate
which python
# Должно показать: /Volumes/LaCie/mcp/project-scanner/venv/bin/python
```

### ChromaDB все еще не работает

Проверьте версию Python внутри venv:
```bash
source venv/bin/activate
python --version
```

Если показывает 3.14 - пересоздайте venv с 3.12!
