import requests
import re
resp = requests.get('https://html.duckduckgo.com/html/?q=inşaat', headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0'})
print('Len:', len(resp.text), 'Links:', len(re.findall(r'class=\"result__a\"', resp.text)))
