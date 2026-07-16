#!/usr/bin/env python3
"""One-shot Word COM convert: argv[1]=src.wpd argv[2]=dest.txt"""
import sys
from pathlib import Path

def main() -> int:
    src, dest = Path(sys.argv[1]), Path(sys.argv[2])
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src), False, True, False)
        # Prefer SaveAs txt for cleaner newlines; also grab Content.Text
        text = doc.Content.Text or ""
        # Word uses \r for paragraph marks
        text = text.replace("\r\x07", "\n").replace("\r", "\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        header = f"SOURCE: {src}\nMETHOD: word_com_wpd\nCHARS: {len(text)}\n\n"
        dest.write_text(header + text, encoding="utf-8", errors="ignore")
        doc.Close(False)
        print(json_ok(len(text)))
        return 0
    except Exception as e:
        print(f"ERR {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        if word is not None:
            try:
                word.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass

def json_ok(n):
    import json
    return json.dumps({"ok": True, "chars": n})

if __name__ == "__main__":
    raise SystemExit(main())
