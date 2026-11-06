"""Экспертные оценки из страницы разметки (label.html → «Скачать оценки (JSON)») → ml/labels/expert_labels.xlsx.

Запуск (из папки ml):  python src/import_labels.py путь/к/expert_labels_Имя.json [ещё файлы …]
Можно передать несколько файлов от разных людей: оценки складываются; если один человек оценил здание
дважды, берётся последняя оценка. После этого снова запустите build_model.py — при ≥ 60 оценках
модель проверится на согласие с экспертами и дообучится.
"""
import json, os, sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import ML  # noqa: E402

OUT = ML / "labels" / "expert_labels.xlsx"
VALID = {"Хорошо", "Средне", "Плохо", "Не знаю"}


def read_json(path):
    d = json.load(open(path, encoding="utf-8"))
    rows = d["labels"] if isinstance(d, dict) else d
    who_file = d.get("who", "") if isinstance(d, dict) else ""
    out = []
    for r in rows:
        if r.get("label") not in VALID:
            continue
        out.append({"osm_id": int(r["osm_id"]), "адрес": r.get("address", ""), "оценка": r["label"],
                    "комментарий": r.get("comment", ""), "кто": r.get("who") or who_file or "аноним",
                    "когда": r.get("ts", ""), "файл": os.path.basename(path)})
    return out


def main(paths):
    rows = []
    for p in paths:
        rows += read_json(p)
    new = pd.DataFrame(rows, columns=["osm_id", "адрес", "оценка", "комментарий", "кто", "когда", "файл"])
    if OUT.exists():   # добавляем к уже собранным оценкам
        new = pd.concat([pd.read_excel(OUT), new], ignore_index=True)
    new = new.sort_values("когда").drop_duplicates(["osm_id", "кто"], keep="last").reset_index(drop=True)
    OUT.parent.mkdir(exist_ok=True)
    new.to_excel(OUT, index=False, sheet_name="Оценки экспертов")
    usable = new[new["оценка"] != "Не знаю"]
    print(f"Оценок всего: {len(new)}, пригодных (без «Не знаю»): {len(usable)}, зданий: {usable['osm_id'].nunique()}")
    print(usable["оценка"].value_counts().to_string())
    print("Сохранено:", OUT)
    if len(usable) < 60:
        print("Для проверки и дообучения модели нужно не меньше 60 оценок.")
    return new


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1:])
