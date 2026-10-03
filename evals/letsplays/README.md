# Летсплеи YouTube: замороженный набор `YTP-02`

Набор оценки Bonus 1 (`YT-01`), заморожен до реализации. Определения, метрика, планка,
рубрика заключения и бюджеты — в [`metric.md`](metric.md).

| Файл | Что это |
|---|---|
| [`candidates.json`](candidates.json) | Пулы кандидатов 20 игр с просмотрами и длительностью (публичные метаданные) |
| [`labels.json`](labels.json) | 93 метки и ожидаемый ролик для каждой игры |
| [`baseline_report.json`](baseline_report.json) | Два опорных селектора; оба не проходят планку |
| [`conclusion_cases.json`](conclusion_cases.json) | 14 случаев для заключения: источник, число слов, SHA-256 текста, ожидаемый статус |
| [`score_selection.py`](score_selection.py) | Скоринг выбора; без аргументов пересчитывает опорные варианты |
| [`test_score_selection.py`](test_score_selection.py) | Контрпримеры для скоринга |
| [`collect.py`](collect.py), [`build_labels.py`](build_labels.py), [`freeze_inputs.py`](freeze_inputs.py) | Как собраны пул, метки и входы заключения |
| [`host_captions.sh`](host_captions.sh), [`check_speech.py`](check_speech.py) | Проверка речи и языка по субтитрам (с сервера) и по аудио (Whisper) |

Тексты роликов — сторонний материал, хранятся вне Git в `.artifacts/ytp02/`. Это исследовательский
инструментарий, а не тесты приложения; живые вызовы YouTube и Groq в CI не выполняются.

```powershell
.\.venv-app\Scripts\python.exe -B evals/letsplays/score_selection.py
.\.venv-app\Scripts\python.exe -B -m unittest discover -s evals/letsplays -p "test_*.py"
```
