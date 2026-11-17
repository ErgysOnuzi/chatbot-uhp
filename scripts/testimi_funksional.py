"""Testimi funksional i chatbot-it (seksioni 6.3 i punimit).

    python scripts\\testimi_funksional.py --fjalekalimi FJALEKALIMI_I_ADMINIT

Kryen 9 teste kundër sistemit që punon dhe shkruan rezultatin në
scripts/rezultatet/testimi_funksional.md. Për çdo test shtyp "Kaloi" ose "Dështoi".
Testi i fundit (kufiri i pyetjeve) dërgon pyetje jashtë fushës, që nuk e thërrasin
modelin gjuhësor, prandaj nuk kushton asgjë.
"""

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_OF_SCOPE = "Kush e fitoi Kupën e Botës në futboll 2022?"
CODEWORD = "Zebra-7341"


def request(base, method, path, body=None, token=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = dict(headers or {})
    if body is not None:
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, r.read().decode("utf-8"), r.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), exc.headers


def chat(base, message, conversation_id=None):
    start = time.perf_counter()
    status, text, _ = request(base, "POST", "/api/chat", {"message": message, "conversation_id": conversation_id})
    events = [json.loads(l) for l in text.splitlines() if l.strip()] if status == 200 else []
    meta = next((e for e in events if e["type"] == "meta"), {})
    done = next((e for e in events if e["type"] == "done"), {})
    tokens = [e for e in events if e["type"] == "token"]
    return {
        "status": status,
        "answer": "".join(e["text"] for e in tokens),
        "tokens": len(tokens),
        "sources": [s["title"] for s in meta.get("sources", [])],
        "conversation_id": meta.get("conversation_id"),
        "message_id": done.get("message_id"),
        "answered": done.get("answered"),
        "seconds": round(time.perf_counter() - start, 2),
    }


def multipart(fields, filename, content):
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n".encode() + content + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost")
    parser.add_argument("--perdoruesi", default="admin")
    parser.add_argument("--fjalekalimi", required=True)
    args = parser.parse_args()
    base = args.url.rstrip("/")
    results = []

    def record(req, scenario, ok, detail):
        results.append((req, scenario, "Kaloi" if ok else "Dështoi", detail))
        print(f"{'Kaloi  ' if ok else 'DËSHTOI'}  {req}: {scenario} ({detail})")

    # KF-01, KF-06: përgjigje që vjen pjesë-pjesë
    r = chat(base, "Sa kushton dublikata e diplomës?")
    record("KF-01, KF-06", "Bëhet një pyetje; përgjigjja shfaqet gradualisht", r["status"] == 200 and r["tokens"] > 1,
           f"{r['tokens']} pjesë teksti në {r['seconds']} s")
    # KF-03: burimi
    record("KF-03", "Te përgjigjja shfaqet burimi", bool(r["sources"]), "; ".join(r["sources"]) or "pa burim")
    first_message_id = r["message_id"]

    time.sleep(7)
    # KF-04: jashtë fushës
    r = chat(base, OUT_OF_SCOPE)
    record("KF-04", "Pyetje jashtë dokumenteve; shfaqet përgjigjja standarde", r["status"] == 200 and r["answered"] is False, r["answer"][:80])

    time.sleep(7)
    # KF-05: pyetje vijuese
    r1 = chat(base, "Kur fillon semestri veror?")
    time.sleep(7)
    r2 = chat(base, "Po semestri dimëror, kur mbaron?", r1["conversation_id"])
    record("KF-05", 'Pyetje vijuese pas një pyetjeje për semestrat', r2["answered"] is True and "15" in r2["answer"],
           r2["answer"][:80].replace("\n", " "))

    # KF-07: vlerësimi
    status, _, _ = request(base, "POST", f"/api/messages/{first_message_id}/feedback", {"value": 1})
    login_status, login_body, _ = request(base, "POST", "/api/admin/login", {"username": args.perdoruesi, "password": args.fjalekalimi})
    token = json.loads(login_body).get("token") if login_status == 200 else None
    stats = json.loads(request(base, "GET", "/api/admin/stats", token=token)[1]) if token else {}
    record("KF-07", 'Vlerësimi "Po/Jo" shfaqet në statistika', status == 200 and stats.get("feedback_positive", 0) >= 1,
           f"vlerësime pozitive: {stats.get('feedback_positive')}")

    # KF-09: fjalëkalim i gabuar
    bad, _, _ = request(base, "POST", "/api/admin/login", {"username": args.perdoruesi, "password": "gabim-" + uuid.uuid4().hex})
    record("KF-09", "Kyçja me fjalëkalim të gabuar refuzohet", bad == 401 and token is not None, f"HTTP {bad}; kyçja e saktë: {login_status}")

    # KF-10: ngarkimi i një dokumenti testues me një fjalë kodi
    title = f"Dokument testues {CODEWORD}"
    content = f"Fjala sekrete e laboratorit të fakultetit për testim është {CODEWORD}.".encode("utf-8")
    raw, headers = multipart({"title": title, "category": "Test"}, "test.txt", content)
    up_status, up_body, _ = request(base, "POST", "/api/admin/documents", token=token, headers=headers, raw=raw)
    doc_id = json.loads(up_body).get("id") if up_status == 200 else None
    time.sleep(7)
    r = chat(base, "Cila është fjala sekrete e laboratorit të fakultetit për testim?")
    record("KF-10", "Ngarkohet dokument; chatbot-i përgjigjet nga ai", doc_id is not None and CODEWORD in r["answer"],
           f"ngarkimi HTTP {up_status}, përgjigjja: {r['answer'][:60]}")

    # KF-12: fshirja
    del_status, _, _ = request(base, "DELETE", f"/api/admin/documents/{doc_id}", token=token) if doc_id else (None, "", None)
    time.sleep(7)
    r = chat(base, "Cila është fjala sekrete e laboratorit të fakultetit për testim?")
    record("KF-12", "Fshirja e dokumentit; pyetjet për të nuk gjejnë më përgjigje", del_status == 200 and r["status"] == 200 and CODEWORD not in r["answer"],
           f"fshirja HTTP {del_status}, u gjet: {r['answered']}")

    # KJF-05: kufiri i pyetjeve (pyetje jashtë fushës nuk e thërrasin LLM-në)
    print("Pres 60 sekonda që të pastrohet kufiri, pastaj dërgoj 11 pyetje njëra pas tjetrës...")
    time.sleep(60)
    codes = [chat(base, OUT_OF_SCOPE)["status"] for _ in range(11)]
    record("KJF-05", "Pyetja e 11-të brenda një minute refuzohet me kodin 429", codes[:10].count(200) == 10 and codes[10] == 429,
           f"kodet: {codes}")

    out = HERE / "rezultatet"
    out.mkdir(exist_ok=True)
    lines = ["| Kërkesa | Skenari i testimit | Rezultati | Detaje |", "| --- | --- | --- | --- |"]
    lines += [f"| {a} | {b} | {c} | {d.replace('|', '/')} |" for a, b, c, d in results]
    (out / "testimi_funksional.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nKaluan {sum(r[2] == 'Kaloi' for r in results)} / {len(results)}. Ruajtur te {out / 'testimi_funksional.md'}")


if __name__ == "__main__":
    main()
