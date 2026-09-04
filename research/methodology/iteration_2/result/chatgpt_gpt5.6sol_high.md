Готово. Я детально сопоставил обе итерации с исходным заданием: почасовой/дневной цикл и обновление данных , обязательный UI и похожие игры , обе дополнительные части и комплект сдачи .

В финальной версии я сохранил сильные стороны `iteration_1` — risk-driven процесс, acceptance matrix, vertical slices, AI evals, failure/concurrency testing и Definition of Done — и дополнил их результатами всех вариантов `iteration_0`. При этом убрал рекомендации, которые уже являлись проектированием конкретного решения: обязательные очереди, конкретные схемы БД, Docker/feature branches/semver и т. п.

Главное усиление итоговой версии — **evidence-driven methodology**: существенное требование считается закрытым не после написания кода, а когда для него определены acceptance criteria и есть доказательство выполнения через test / AI eval / log / metric / E2E / public smoke check.

[`methodology.md`]

Документ получился подробным: 19 разделов, включая ревью итераций, requirements traceability, risk spikes, последовательность разработки, идемпотентность и календарную семантику, defensive scraping, отдельный AI-quality process, similarity eval, E2E, observability, тестовую стратегию, CI/delivery, security, AI-артефакты и полный Definition of Done.

Следующий логичный шаг — на базе этого `methodology.md` сделать компактный `acceptance_checklist.md`, который уже можно использовать непосредственно во время реализации и перед финальной сдачей.
