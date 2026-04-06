import requests
import re
resp = requests.get('https://html.duckduckgo.com/html/?q=inşaat', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0'})
with open('ddg_error.html', 'w', encoding='utf-8') as f:
    f.write(resp.text)
