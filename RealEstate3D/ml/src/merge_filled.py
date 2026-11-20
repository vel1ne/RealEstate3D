"""Объединение двух заполненных версий датасета ГКО 2023 (склады и производство > 100 м²).

  A — версия из НСПД (файл от команды, Telegram): актуальные сведения, пометки «ОБЪЕКТ НЕ НАЙДЕН»;
  B — наша версия из перечня ГКО 2023 (fill_from_gko.py): этажи, год, адрес на 01.01.2023, координаты дома из OSM.

Правила (ничего не придумываем, только переносим):
  • Адрес — из A (НСПД, актуальный, в том числе «ОБЪЕКТ НЕ НАЙДЕН»), если в A пусто — из B.
  • Этажи, год — из A, если в A пусто — из B. Расхождения записываются на лист «Сравнение».
  • Координаты — из B (найден именно дом), если в B пусто — из A. Расхождение больше 1 км — на проверку.
Результат: «…_объединено.xlsx» рядом с файлом B; исходные файлы не меняются.

Запуск:  python src/merge_filled.py <файл A> <файл B>
         python src/merge_filled.py --arbitrate <…_объединено.xlsx>   — рассудить координаты через DaData
"""
import math, re, sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill

COL = {"floors": 4, "year": 5, "addr": 6, "coords": 7}
NF = "ОБЪЕКТ НЕ НАЙДЕН"


def rows(ws):
    return {str(ws.cell(r, 2).value).strip(): r for r in range(2, ws.max_row + 1) if ws.cell(r, 2).value}


def ll(s):
    m = re.match(r"\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)", str(s or ""))
    return (float(m.group(1)), float(m.group(2))) if m else None


def dist(p, q):
    return math.hypot((p[0] - q[0]) * 111_000, (p[1] - q[1]) * 111_000 * math.cos(math.radians(p[0])))


def empty(v):
    return v is None or str(v).strip() == ""


def main(path_a, path_b):
    a_wb, b_wb = openpyxl.load_workbook(path_a), openpyxl.load_workbook(path_b)
    A, B = a_wb.worksheets[0], b_wb.worksheets[0]
    ra, rb = rows(A), rows(B)
    out = b_wb   # берём файл B как основу: в нём уже есть «Журнал заполнения»
    W = out.worksheets[0]
    if "Сравнение" in out.sheetnames:
        del out["Сравнение"]
    cmp_ws = out.create_sheet("Сравнение", 1)
    cmp_ws.append(["Строка", "Кадастровый номер", "Поле", "Значение НСПД (файл команды)", "Значение перечня ГКО 2023 / OSM",
                   "Что взято в таблицу", "Комментарий"])
    st = {k: {"из НСПД": 0, "из перечня/OSM": 0, "совпало": 0, "расхождение": 0} for k in COL}
    st["coords"]["расхождение > 1 км"] = 0
    warn = PatternFill("solid", fgColor="FFF4DE")
    for cn, r in rb.items():
        ia = ra.get(cn)
        if ia is None:
            continue
        for key, c in COL.items():
            va, vb = A.cell(ia, c).value, B.cell(r, c).value
            if empty(va) and empty(vb):
                continue
            if key == "coords":
                take, src = (vb, "перечень/OSM") if not empty(vb) else (va, "НСПД-файл")
                p, q = ll(va), ll(vb)
                if p and q:
                    d = dist(p, q)
                    if d < 1:
                        st[key]["совпало"] += 1
                    else:
                        st[key]["расхождение"] += 1
                        big = d > 1000
                        if big:
                            st[key]["расхождение > 1 км"] += 1
                        cmp_ws.append([r, cn, "Координаты", va, vb, "перечень/OSM",
                                       f"расхождение {d:,.0f} м".replace(",", " ") + (" — ПРОВЕРИТЬ" if big else "")])
                        if big:
                            for cell in cmp_ws[cmp_ws.max_row]:
                                cell.fill = warn
                elif not empty(va) and empty(vb):
                    st[key]["из НСПД"] += 1
                elif not empty(vb):
                    st[key]["из перечня/OSM"] += 1
            else:
                take, src = (va, "НСПД-файл") if not empty(va) else (vb, "перечень ГКО 2023")
                if not empty(va) and not empty(vb):
                    if str(va).strip() == str(vb).strip():
                        st[key]["совпало"] += 1
                    else:
                        st[key]["расхождение"] += 1
                        note = "в НСПД объекта сейчас нет (снят с учёта); адрес на 01.01.2023 — справа" \
                            if key == "addr" and str(va).strip() == NF else ""
                        cmp_ws.append([r, cn, {"floors": "Этажей", "year": "Год постройки", "addr": "Адрес"}[key],
                                       va, vb, "НСПД", note])
                elif not empty(va):
                    st[key]["из НСПД"] += 1
                else:
                    st[key]["из перечня/OSM"] += 1
            W.cell(r, c).value = take
    for cell in cmp_ws[1]:
        cell.font = Font(bold=True)
    for col, w in zip("ABCDEFG", [8, 22, 14, 48, 48, 16, 50]):
        cmp_ws.column_dimensions[col].width = w
    cmp_ws.freeze_panes = "A2"
    res = Path(path_b).with_name(Path(path_b).stem.replace("_заполнено", "") + "_объединено.xlsx")
    out.save(res)
    filled = {k: sum(1 for r in rb.values() if not empty(W.cell(r, c).value)) for k, c in COL.items()}
    nf = sum(1 for r in rb.values() if str(W.cell(r, COL["addr"]).value).strip() == NF)
    print("готово:", res)
    print("заполнено:", filled, "| «ОБЪЕКТ НЕ НАЙДЕН»:", nf)
    for k, v in st.items():
        print(" ", k, v)


def arbitrate(path_merged, near_m=300):
    """DaData как судья (адреса ФИАС/ГАР, только точное попадание в дом, qc_geo=0). Основа — OSM:
      • для строк, где координаты команды и наши (OSM) расходятся больше 1 км, точку OSM меняем на точку
        команды, только если DaData подтверждает точку команды (в пределах near_m и ближе, чем OSM);
      • для строк без координат — ставим точку DaData, если она точная.
    Решение по каждой строке пишется на лист «Сравнение» (колонки H–I)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import json
    import fill_from_gko as fg
    key = fg.dadata_key()
    if not key:
        raise SystemExit("Нет ключа DaData: создайте файл ml/.env со строкой DADATA_API_KEY=ваш_ключ")
    wb = openpyxl.load_workbook(path_merged)
    W, C = wb.worksheets[0], wb["Сравнение"]
    cache = json.loads(fg.DADATA_CACHE.read_text(encoding="utf-8")) if fg.DADATA_CACHE.exists() else {}
    C.cell(1, 8).value, C.cell(1, 9).value = "DaData (точно дом)", "Решение"
    for cell in (C.cell(1, 8), C.cell(1, 9)):
        cell.font = Font(bold=True)
    C.column_dimensions["H"].width, C.column_dimensions["I"].width = 26, 60
    st = {"выбрана точка команды": 0, "выбрана наша точка": 0,
          "DaData не уверена — оставлено как было": 0, "добавлены пропуски": 0, "пропуск остался": 0}

    def dd(addr):
        g = fg.geocode_dadata("Саратовская область, " + addr if "саратов" not in addr.lower()[:30] else addr, key, cache)
        if g and "error" in g and g["error"] in ("HTTP 401", "HTTP 403"):
            raise SystemExit("DaData не принимает ключ: " + g["error"])
        if g and g.get("qc_geo") == "0" and g.get("lat"):
            return (float(g["lat"]), float(g["lon"])), g["value"]
        return None, (g or {}).get("value", "не найдено") if g and "error" not in g else (g or {}).get("error", "не найдено")

    # 1) спорные (> 1 км)
    for row in range(2, C.max_row + 1):
        if C.cell(row, 3).value != "Координаты" or "ПРОВЕРИТЬ" not in str(C.cell(row, 7).value or ""):
            continue
        r = C.cell(row, 1).value
        addr = str(W.cell(r, COL["addr"]).value or "")
        if not addr or addr == NF:
            C.cell(row, 9).value = "адреса нет — не проверить"
            continue
        pt, txt = dd(addr)
        team, ours = ll(C.cell(row, 4).value), ll(C.cell(row, 5).value)
        if pt is None:
            st["DaData не уверена — оставлено как было"] += 1
            C.cell(row, 9).value = f"DaData не нашла дом точно ({txt}) — оставлена наша точка"
            continue
        C.cell(row, 8).value = f"{pt[0]:.6f}, {pt[1]:.6f}"
        dt, do = dist(pt, team), dist(pt, ours)
        # основа — OSM: нашу точку меняем на точку команды, только если DaData подтверждает именно её
        if dt <= near_m and dt < do:
            win = C.cell(row, 4).value
            st["выбрана точка команды"] += 1
            C.cell(row, 9).value = f"DaData подтверждает точку команды: {dt:,.0f} м против {do:,.0f} м у OSM".replace(",", " ")
        else:
            win = C.cell(row, 5).value
            st["выбрана наша точка"] += 1
            C.cell(row, 9).value = (f"оставлена точка OSM ({do:,.0f} м до DaData, у команды {dt:,.0f} м)"
                                    + ("" if do <= near_m else " — обе далеко от DaData, проверить вручную")).replace(",", " ")
        W.cell(r, COL["coords"]).value = win
    # 2) пропуски
    for r in range(2, W.max_row + 1):
        addr = str(W.cell(r, COL["addr"]).value or "")
        if not W.cell(r, 2).value or W.cell(r, COL["coords"]).value or not addr or addr == NF:
            continue
        pt, txt = dd(addr)
        if pt:
            W.cell(r, COL["coords"]).value = f"{pt[0]:.6f}, {pt[1]:.6f}"
            st["добавлены пропуски"] += 1
            C.append([r, W.cell(r, 2).value, "Координаты", None, None, "DaData", "пропуск заполнен (точно дом): " + txt])
        else:
            st["пропуск остался"] += 1
    wb.save(path_merged)
    print("DaData:", st)


if __name__ == "__main__":
    if sys.argv[1] == "--arbitrate":
        arbitrate(sys.argv[2])
    else:
        main(sys.argv[1], sys.argv[2])
