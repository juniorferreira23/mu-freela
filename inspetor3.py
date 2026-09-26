from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    nav = p.chromium.connect_over_cdp("http://localhost:9223")
    ctxs = nav.contexts
    print("Contexts:", len(ctxs))
    for c in ctxs:
        for pg in c.pages:
            print(" -", pg.url)
    # via CDP cru, listar todos os alvos
    sess = nav.contexts[0].new_cdp_session(nav.contexts[0].pages[0]) if ctxs and ctxs[0].pages else None
    nav.close()

# acesso http direto a outros endpoints
import urllib.request
for ep in ["/json", "/json/list", "/json/tabs"]:
    try:
        print(ep, "=>", urllib.request.urlopen("http://localhost:9223" + ep, timeout=5).read().decode()[:500])
    except Exception as e:
        print(ep, "ERRO", e)
