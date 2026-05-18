"""
Скрипт для запуска оценки RAG с поддержкой faithfulness.
Запускает evaluate_rag с параметрами из командной строки.
"""
import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.rag_evaluator import evaluate_rag, get_last_metrics


def main():
    parser = argparse.ArgumentParser(description="Оценка RAG с поддержкой faithfulness")
    parser.add_argument("--evaluate-faithfulness", action="store_true",
                        help="Включить оценку faithfulness")
    parser.add_argument("--faithfulness-sample-size", type=int, default=50,
                        help="Размер выборки для faithfulness (по умолчанию 50)")
    parser.add_argument("--ci", action="store_true",
                        help="CI-режим: faithfulness на 25 вопросах, выход с кодом 1 если < 4.0")
    parser.add_argument("--dataset", type=str, default=None,
                        help="Путь к датасету")
    parser.add_argument("--k", type=str, default="1,3,5",
                        help="Список k через запятую (по умолчанию 1,3,5)")
    parser.add_argument("--show-last", action="store_true",
                        help="Показать последние метрики и выйти")

    args = parser.parse_args()

    if args.show_last:
        metrics = get_last_metrics()
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return

    k_list = [int(k.strip()) for k in args.k.split(",")]

    print(f"Запуск оценки RAG...")
    print(f"  Датасет: {args.dataset or 'по умолчанию'}")
    print(f"  k: {k_list}")
    print(f"  Faithfulness: {'включена' if args.evaluate_faithfulness else 'выключена'}")
    if args.evaluate_faithfulness:
        print(f"  Размер выборки faithfulness: {args.faithfulness_sample_size}")
    if args.ci:
        print(f"  CI-режим: ДА")

    result = evaluate_rag(
        dataset_path=args.dataset,
        k_list=k_list,
        evaluate_faithfulness=args.evaluate_faithfulness,
        faithfulness_sample_size=args.faithfulness_sample_size,
        ci=args.ci
    )

    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТЫ ОЦЕНКИ RAG:")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # CI-режим
    if args.ci and result.get("ci_failed"):
        print("\n❌ CI НЕ ПРОЙДЕН: faithfulness ниже порога 4.0")
        sys.exit(1)
    elif args.ci:
        print("\n✅ CI ПРОЙДЕН")

    # Сохраняем в файл для удобства
    output_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", "rag_evaluation_result.json"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nРезультат сохранён в {output_path}")


if __name__ == "__main__":
    main()
