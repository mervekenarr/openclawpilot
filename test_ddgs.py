from duckduckgo_search import DDGS

query = "inşaat istanbul site:linkedin.com/company"
try:
    with DDGS() as ddgs:
        results = [r for r in ddgs.text(query, max_results=5)]
        print(len(results), results)
except Exception as e:
    print("Error:", e)
