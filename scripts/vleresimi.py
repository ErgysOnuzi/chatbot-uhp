"""Vlerësimi automatik i chatbot-it me 20 pyetjet testuese (Shtojca A e punimit).

Përdor vetëm libraritë standarde të Python-it, prandaj punon direkt në Windows:

    python scripts\\vleresimi.py --emri deepseek
    python scripts\\vleresimi.py --emri ollama-qwen2.5-3b

Për secilën pyetje mat kohën deri te fjala e parë dhe kohën totale, dhe ruan
përgjigjen, burimet dhe nëse chatbot-i e gjeti përgjigjen. Rezultatet ruhen në
scripts/rezultatet/<emri>.csv dhe <emri>.md. Kolona "Vleresimi" (S/P/G/R)
plotësohet nga ti pasi t'i lexosh përgjigjet.
"""

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ask(base_url: str, question: str, conversation_id: str | None) -> dict:
    body = json.dumps({"message": question, "conversation_id": conversation_id}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/chat",
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "chatbot-uhp-evaluation/0.1",
        },
        method="POST",
    )
    start = time.perf_counter()
    first_token = None
    result = {"answer": "", "sources": [], "answered": None, "conversation_id": conversation_id, "error": ""}
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw in response:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            event = json.loads(line)
            if event["type"] == "meta":
                result["conversation_id"] = event["conversation_id"]
                result["sources"] = [s["title"] for s in event["sources"]]
            elif event["type"] == "token":
                if first_token is None:
                    first_token = time.perf_counter() - start
                result["answer"] += event["text"]
            elif event["type"] == "error":
                result["error"] = event["text"]
            elif event["type"] == "done":
                result["answered"] = event["answered"]
    result["first_token_s"] = round(first_token, 2) if first_token is not None else None
    result["total_s"] = round(time.perf_counter() - start, 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Vlerësimi i chatbot-it me pyetjet testuese")
    parser.add_argument("--emri", required=True, help="Emri i modelit për skedarin e rezultateve, p.sh. deepseek")
    parser.add_argument("--url", default="http://localhost", help="Adresa e chatbot-it (parazgjedhje: http://localhost)")
    parser.add_argument("--pauza", type=float, default=7.0, help="Sekonda ndërmjet pyetjeve (kufiri është 10 pyetje/min)")
    args = parser.parse_args()

    questions = json.loads((HERE / "pyetjet_testuese.json").read_text(encoding="utf-8"))
    out_dir = HERE / "rezultatet"
    out_dir.mkdir(exist_ok=True)
    rows = []
    conversation_id = None

    for q in questions:
        if not q.get("vijuese"):
            conversation_id = None  # bisedë e re për çdo pyetje, përveç pyetjeve vijuese
        print(f"[{q['nr']:>2}/20] {q['pyetja']}")
        for attempt in range(3):
            try:
                r = ask(args.url, q["pyetja"], conversation_id)
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    print("       Kufiri i pyetjeve, po pres 60 sekonda...")
                    time.sleep(60)
                    continue
                r = {"answer": "", "sources": [], "answered": None, "error": f"HTTP {exc.code}", "first_token_s": None, "total_s": None, "conversation_id": None}
                break
            except Exception as exc:
                r = {"answer": "", "sources": [], "answered": None, "error": str(exc), "first_token_s": None, "total_s": None, "conversation_id": None}
                break
        conversation_id = r.get("conversation_id")
        status = "gabim: " + r["error"] if r["error"] else ("me përgjigje" if r["answered"] else "pa përgjigje")
        print(f"       {status}, fjala e parë pas {r['first_token_s']} s")
        rows.append({
            "Nr": q["nr"],
            "Kategoria": q["kategoria"],
            "Pyetja": q["pyetja"],
            "Pritet": q["pritet"],
            "Pergjigjja": r["answer"].strip(),
            "Burimet": "; ".join(r["sources"]),
            "U_gjet": {True: "po", False: "jo", None: ""}[r["answered"]],
            "Fjala_e_pare_s": r["first_token_s"],
            "Koha_totale_s": r["total_s"],
            "Gabim": r["error"],
            "Vleresimi": "",
        })
        time.sleep(args.pauza)

    csv_path = out_dir / f"{args.emri}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig që Excel t'i shfaqë shkronjat shqipe
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    times = [r["Fjala_e_pare_s"] for r in rows if r["Fjala_e_pare_s"] is not None]
    md = [f"# Rezultatet e vlerësimit: {args.emri}", ""]
    md.append(f"- Pyetje me përgjigje: {sum(r['U_gjet'] == 'po' for r in rows)} / {len(rows)}")
    md.append(f"- Pyetje pa përgjigje (refuzime): {sum(r['U_gjet'] == 'jo' for r in rows)}")
    md.append(f"- Gabime teknike: {sum(bool(r['Gabim']) for r in rows)}")
    if times:
        md.append(f"- Koha mesatare deri te fjala e parë: {sum(times) / len(times):.2f} s")
    md.append("")
    for r in rows:
        md += [f"## {r['Nr']}. {r['Pyetja']}", f"*Pritet:* {r['Pritet']}  ", f"*Burimet:* {r['Burimet'] or '–'}  ",
               f"*Koha:* {r['Fjala_e_pare_s']} s / {r['Koha_totale_s']} s", "", r["Pergjigjja"] or f"(gabim: {r['Gabim']})", ""]
    (out_dir / f"{args.emri}.md").write_text("\n".join(md), encoding="utf-8")
    print(f"\nRuajtur: {csv_path} dhe {out_dir / (args.emri + '.md')}")


if __name__ == "__main__":
    main()
