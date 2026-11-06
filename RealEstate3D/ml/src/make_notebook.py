"""Ноутбук для Colab (ml/notebooks/warehouse_sites.ipynb) и архив проекта для загрузки (ml/out/warehouse_model_colab.zip).
Локальная проверка кода ноутбука на части города:  python src/make_notebook.py --test <пустая папка>
"""
import json, os, subprocess, sys, zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import DE_SQLITE, ML, OSM, OUT  # noqa: E402

CELLS = [
("md", """# Где ставить склад в Саратове: модель оценивает каждое здание

**Задача:** обучить модель, которая по дорожной ситуации и окружению сама оценивает, насколько здание подходит под склад, и показать лучшие зоны и здания Саратова. Пользователь стартапа вводит адрес объявления — получает оценку и объяснение.

| Данные | Откуда |
|---|---|
| Дороги, узлы, запреты поворотов, препятствия | база дата-инженера `data_engineering/data/processed/saratov_roads.sqlite` (OSM, 27.10.2026), только чтение |
| Скорости и загруженность | модель коллеги «модель дорог» (Colab): коэффициенты 0.85 / 0.75 / 0.95 / 0.9, штрафы за повороты 1 / 1 / 0.5 мин |
| Здания, промзоны, ж/д, школы, магазины, жилые кварталы | OpenStreetMap (скачано заранее, `ml/data/osm`) |

**Шаги:** граф для фуры → признаки каждого здания (выезд, последняя миля, окружение, доступность города, ж/д) → обучение 4 моделей и честная проверка на незнакомых районах → итоговый балл с правилами безопасности и профилями → зоны → карта, Excel, отчёт.

**Запуск:** *Среда выполнения → Выполнить все*, на первом шаге загрузите `warehouse_model_colab.zip`. Полный расчёт ≈ 10–15 минут."""),

("code", """# Шаг 0. Загрузка проекта (архив warehouse_model_colab.zip)
!pip install -q shapely scikit-learn openpyxl joblib
import os, sys, zipfile
from google.colab import files
up = files.upload()
zipfile.ZipFile(list(up)[0]).extractall("/content")
os.chdir("/content/RealEstate3D/ml")
sys.path.insert(0, "src")
FAST = False      # True — без подбора гиперпараметров (≈ 3 мин вместо 10–15)
TEST_RUN = False  # True — только часть города (проверка)
print("Проект распакован:", os.listdir("."))"""),

("md", """## Шаг 1. Признаки, обучение и проверка

**Что считается для каждого здания** (это описание *места*, а не здания):
- **выезд из города** — время фуры до СКАД и каждого выезда, туда и обратно, лучший и запасной;
- **последняя миля** — реальный путь фуры по графу до ближайшей магистрали: длина, время, доля по жилым улицам и дворам, повороты, тупик, односторонние и узкие участки, ограничения рядом;
- **окружение** — жилые дома в 100/200/500 м, школы и больницы, плотность дорог, центр;
- **достижимость города** — время до 200 центров спроса (кластеры жилья и магазинов OSM);
- **ж/д и свободное место** вокруг здания.

Тип здания, landuse, тег склада и площадь в признаки **не входят** — из них строится метка.

**Метка:** A — склады/производства и нежилые здания в промзонах против всех остальных; B — те же против жилых домов. **Модели:** формула с ручными весами, логистическая регрессия, бустинг, бустинг с монотонными ограничениями. **Проверка:** блоки 3×3 км — модель оценивается на районах, которых не видела."""),

("code", """import pandas as pd, numpy as np
from IPython.display import display, HTML
import build_model as bm, train_model as tm, features as F
pd.set_option("display.max_colwidth", 120)
S = bm.main(fast=FAST, test=TEST_RUN)
display(pd.Series({k: v for k, v in S["report"].items() if not isinstance(v, (dict, list))}).to_frame("Значение"))"""),

("code", """# Таблица «модель × метрика» (среднее ± разброс по районам). A и B — варианты метки.
import reports
display(reports.quality_table(S))
s = S["summary"].set_index(["variant", "model"]); fin = S["report"]["Итоговая модель"]
display(HTML(f"<p><b>Итоговая модель:</b> {tm.MODEL_RU[fin]}. Average Precision {s.loc[('A', fin), 'ap']:.3f} против "
             f"{s.loc[('A', 'formula'), 'ap']:.3f} у формулы (в {s.loc[('A', fin), 'ap'] / s.loc[('A', 'formula'), 'ap']:.1f} раза лучше); "
             f"ROC-AUC {s.loc[('A', fin), 'roc_auc']:.3f} против {s.loc[('A', 'formula'), 'roc_auc']:.3f}.</p>"))"""),

("code", """# Что даёт каждая группа признаков (модель обучали заново без группы) и важные признаки
display(S["ablation"].assign(group=lambda d: d["group"].map(lambda g: F.GROUP_RU.get(g, g))).round(4))
imp = S["importance"].head(15).rename(index=F.FEATURE_RU).to_frame("падение AP, если перемешать признак")
display(imp)"""),

("code", """# Ошибки модели: 20 «ложных отлично» и 20 пропущенных складов
display(S["errors"][["ошибка", "addr_full", "type_ru", "area_m2", "ml", "что это за место"]])"""),

("md", """## Шаг 2. Итоговый балл, правила и зоны

**Итог здания** = 0.7 × балл модели («лучше, чем X% зданий города») + 0.3 × формула профиля (выезд / город / последняя миля / здание / ж/д и кластер). Поверх — правила безопасности: нет проезда ≤ 20, подъезд по жилым дворам ≤ 40, жилой дом ≤ 30, здание без типа в жилом квартале ≤ 40, меньше 100 м² ≤ 50. Все числа — в `config/warehouse_config.json`."""),

("code", """display(S["zones_table"][["Зона", "Балл (лучшее здание)", "Улицы", "Площадь, га", "Отличных зданий (≥ 75)",
                         "Лучшее здание", "Почему", "Предупреждения"]].head(15))"""),

("code", """# Карточки зданий — то же, что при клике на карте (координаты: правый клик в Яндекс/Google Картах)
TEST_PLACES = {
    "ТЦ «Хэппи Молл» (Вольский тракт, 2)": (51.62131, 45.97231),
    "Универсальная, 17": (51.60770, 45.95778),
    "Поле за городом": (51.6400, 45.9300),
}
for name, (lat, lon) in TEST_PLACES.items():
    print("—", name); display(pd.Series(bm.point_report(lat, lon)).to_frame(name))"""),

("code", """# Оценка по адресу объявления (сначала адреса OSM, затем Nominatim)
display(pd.Series(bm.score_address("Вольский тракт, 1")).to_frame("Вольский тракт, 1"))"""),

("md", """## Шаг 3. Карта

Ссылка откроет карту (работает, пока открыт ноутбук). Также скачаются: **один файл карты** `Карта складов Саратова.html` (открывается двойным щелчком, без архива; без подложки OSM), Excel `warehouse_sites.xlsx`, отчёт `model_report.html` и база `warehouse_results.sqlite`.

На карте: поиск по адресу, профили «Универсальный / Транзит / Город», здания от zoom 15 цветом по баллу, карточки, лучшие зоны, маршруты фуры. Страница **label.html** — разметка зданий экспертами."""),

("code", """import make_map, subprocess, time
make_map.main()
subprocess.Popen(["python", "-m", "http.server", "8765", "--directory", "out/map"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)
try:
    from google.colab.output import eval_js
    url = eval_js("google.colab.kernel.proxyPort(8765)")
    display(HTML(f'<p style="font-size:16px">🗺️ <a href="{url}index.html" target="_blank"><b>Открыть карту складов</b></a> · '
                 f'<a href="{url}label.html" target="_blank">разметка экспертами</a></p>'))
    for f in ["out/" + make_map.SINGLE_NAME, "out/warehouse_sites.xlsx", "out/model_report.html", "out/warehouse_results.sqlite"]:
        files.download(f)
except ImportError:
    print("Не Colab: откройте out/Карта складов Саратова.html двойным щелчком или out/map/«Открыть карту складов.cmd»")"""),

("md", """## Шаг 4 (по желанию). Экспертная разметка

1. Откройте `label.html`, оцените здания кнопками «Хорошо / Средне / Плохо / Не знаю», нажмите «Скачать оценки (JSON)».
2. Загрузите JSON сюда и выполните ячейку ниже — получится `labels/expert_labels.xlsx`.
3. Снова выполните шаг 1: при ≥ 60 оценках модель посчитает согласие с экспертами (Спирмен, точность по классам) и дообучится. Без файла всё работает, в отчёте пометка «экспертной проверки нет»."""),

("code", """# up = files.upload()
# import import_labels; import_labels.main(list(up))"""),
]


def build_notebook():
    nb = {"nbformat": 4, "nbformat_minor": 0,
          "metadata": {"colab": {"provenance": []}, "kernelspec": {"name": "python3", "display_name": "Python 3"},
                       "language_info": {"name": "python"}}, "cells": []}
    for kind, src in CELLS:
        c = {"cell_type": "markdown" if kind == "md" else "code", "metadata": {}, "source": src.splitlines(keepends=True)}
        if kind == "code":
            c.update(execution_count=None, outputs=[])
        nb["cells"].append(c)
    path = ML / "notebooks" / "warehouse_sites.ipynb"
    path.parent.mkdir(exist_ok=True)
    json.dump(nb, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ноутбук:", path)


def build_zip():
    path = OUT / "warehouse_model_colab.zip"
    root = "RealEstate3D/"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ML / "src").glob("*.py")):
            z.write(f, root + "ml/src/" + f.name)
        z.write(ML / "config" / "warehouse_config.json", root + "ml/config/warehouse_config.json")
        for f in sorted(OSM.glob("osm_*.json")) + [OSM / "buildings.json"]:
            z.write(f, root + "ml/data/osm/" + f.name)
        labels = ML / "labels" / "expert_labels.xlsx"
        if labels.exists():
            z.write(labels, root + "ml/labels/expert_labels.xlsx")
        z.write(DE_SQLITE, root + "data_engineering/data/processed/saratov_roads.sqlite")
    print("архив для Colab:", path, f"{path.stat().st_size / 1e6:.1f} МБ")
    return path


def test(zip_path, workdir):
    """Распаковать архив в чистую папку и прогнать код ячеек без Colab (часть города, быстрый режим)."""
    import shutil
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    zipfile.ZipFile(zip_path).extractall(workdir)
    ml = os.path.join(workdir, "RealEstate3D", "ml")
    code = ["import os, sys", f"os.chdir({ml!r})", "sys.path.insert(0, 'src')",
            "def display(x):\n    import pandas as pd\n    print(x.to_string() if isinstance(x, (pd.DataFrame, pd.Series)) else x)",
            "class HTML(str): pass", "FAST, TEST_RUN = True, True"]
    for kind, src in CELLS[2:]:
        if kind != "code":
            continue
        src = "\n".join(l for l in src.splitlines() if not l.startswith("!") and not l.startswith("#"))
        src = src.replace("from IPython.display import display, HTML\n", "")
        src = src.replace('subprocess.Popen(["python", "-m", "http.server", "8765", "--directory", "out/map"],\n'
                          '                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)', "pass")
        code.append(src)
    script = os.path.join(workdir, "nb_test.py")
    open(script, "w", encoding="utf-8").write("\n\n".join(code))
    env = {k: v for k, v in os.environ.items() if k != "WAREHOUSE_ROADS_SQLITE"}
    subprocess.run([sys.executable, "-X", "utf8", script], check=True, env=env, cwd=ml)


if __name__ == "__main__":
    build_notebook()
    z = build_zip()
    if "--test" in sys.argv:
        test(z, sys.argv[sys.argv.index("--test") + 1])
