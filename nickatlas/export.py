import csv
import html
import io
import json
import os
import tempfile
from pathlib import Path

from .models import STATUS


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".nickatlas-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def csv_value(value):
    value = str(value)
    return (
        "'" + value
        if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r"))
        else value
    )


def export_results(path, account, results, annotations=None):
    path = Path(path)
    annotations = annotations or {}
    records = []
    for result in results:
        row = result.data()
        favorite, rejected, note = annotations.get(result.url, (0, 0, ""))
        row.update(favorite=bool(favorite), rejected=bool(rejected), note=note)
        records.append(row)
    suffix = path.suffix.lower()
    if suffix == ".json":
        text = json.dumps(
            {"username": account, "results": records}, ensure_ascii=False, indent=2
        )
    elif suffix == ".csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        keys = [
            "site",
            "url",
            "status",
            "source",
            "reason",
            "checked",
            "favorite",
            "rejected",
            "note",
            "links",
        ]
        writer.writerow(keys)
        writer.writerows([[csv_value(r[k]) for k in keys] for r in records])
        text = "\ufeff" + buffer.getvalue()
    elif suffix == ".html":
        esc = html.escape
        rows = "".join(
            "<tr>"
            + "".join(
                "<td>" + esc(str(v)) + "</td>"
                for v in (
                    r["site"],
                    r["url"],
                    STATUS.get(r["status"], r["status"]),
                    r["reason"],
                    r["note"],
                    "; ".join(
                        link["url"] + " (" + link["evidence"] + ")"
                        for link in r.get("links", [])
                    ),
                )
            )
            + "</tr>"
            for r in records
        )
        text = (
            '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NIX</title><style>body{font:16px system-ui;background:#11151b;color:#e7edf5;padding:32px}table{border-collapse:collapse;width:100%}td,th{padding:12px;text-align:left;border-bottom:1px solid #303946;overflow-wrap:anywhere}h1{font-size:26px}</style><h1>'
            + esc(account)
            + "</h1><p>Совпадение ника не доказывает принадлежность аккаунтов одному человеку.</p><table><thead><tr><th>Сайт</th><th>Профиль</th><th>Статус</th><th>Проверка</th><th>Заметка</th><th>Связи</th></tr></thead><tbody>"
            + rows
            + "</tbody></table></html>"
        )
    else:
        raise ValueError("Выбери формат JSON, CSV или HTML")
    atomic_text(path, text)
