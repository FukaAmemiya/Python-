import requests
ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
r = requests.get("某章节URL", headers=ua)
print(r.status_code, "contentsource" in r.text)   # 测 huaben
print(r.status_code, "ChapterBody"  in r.text)    # 测 sfacg