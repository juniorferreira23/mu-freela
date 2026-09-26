from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    nav = p.chromium.connect_over_cdp("http://localhost:9223")
    sess = nav.new_browser_cdp_session()
    r = sess.send("Target.getTargets")
    for t in r["targetInfos"]:
        print(t["type"], "|", t.get("url", ""), "|", t.get("title", ""))
    nav.close()
