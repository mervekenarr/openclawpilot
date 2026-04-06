from ops.openclaw.engine import search_web_companies
import json

def test():
    print("Test basliyor: 'Klavye üretici' aramasi yapiliyor...")
    results = search_web_companies("Klavye", "Üretici", "İstanbul", "Turkiye", limit=3)
    
    print(f"\nBulunan sonuc sayisi: {len(results)}")
    for i, res in enumerate(results):
        print(f"\n{i+1}. Firma: {res['company_name']}")
        print(f"Web: {res['website']}")
        print(f"Skor: {res['score']}")
        print(f"LinkedIn: {res['is_linkedin']}")
        print(f"Snippet: {res['snippet'][:100]}...")

if __name__ == "__main__":
    test()
