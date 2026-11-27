"""Exercise the bundled home page and its native adapter at phone and tablet window sizes."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright

ui = Path(__file__).resolve().parents[1] / "OriginalUI"
server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(ui)))
Thread(target=server.serve_forever, daemon=True).start()

folder = {"project":"Workspace", "project_id":"builtin"}
picker_calls = 0

def native(payload):
    global picker_calls
    path = payload["path"].split("?")[0]
    if path == "/api/project":
        picker_calls += 1
        if picker_calls == 1:
            return {"cancelled":True}
        folder.update(project="My files",project_id="chosen-folder")
        return dict(folder)
    if path == "/api/state":
        names = ["OmniRoute", "FreeLLMAPI", "Apple Intelligence"]
        return dict(version="1.10.0", lang="ar", brand="smarter", default_gateway=names[0],
                    gateways=[dict(name=n, title=n, installed=True, up=True, can_start=True) for n in names],
                    **folder, efforts=[""], permission_modes=["default"])
    return {"accounts": [], "projects": [], "conversations": [], "models": []}

def check_frame(page, selector):
    box = page.locator(selector).bounding_box()
    width, height = page.viewport_size.values()
    assert box and box["width"] > 0 and box["height"] > 0, selector
    assert box["x"] >= -1 and box["x"] + box["width"] <= width + 1, (selector, box, width)
    assert box["y"] >= -1 and box["y"] + box["height"] <= height + 1, (selector, box, height)

try:
    with sync_playwright() as pw:
        browser = pw.webkit.launch()
        for lang in ("ar", "en"):
            folder.update(project="Workspace",project_id="builtin")
            picker_calls = 0
            page = browser.new_page()
            page.expose_function("mobileReply", native)
            page.add_init_script(script="window.webkit={messageHandlers:{mobile:{postMessage:v=>mobileReply(v)}}};" +
                                 f"localStorage.setItem('aio-lang',JSON.stringify('{lang}'));" +
                                 (ui / "bridge.js").read_text())
            for i,(width,height) in enumerate([(430,932),(320,568),(844,390),(390,316),(744,1133),
                                                (820,1180),(1024,768),(1366,1024),(500,768)]):
                page.set_viewport_size({"width":width,"height":height})
                if i == 0:
                    page.goto(f"http://127.0.0.1:{server.server_port}/index.html")
                    page.wait_for_selector("#gwPills .pill")
                    page.wait_for_function("document.querySelector('#drawerClose') && Array.from(document.styleSheets).some(s=>s.href?.endsWith('responsive.css'))")
                    assert page.locator('html').get_attribute('lang') == lang
                page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")
                compact = width <= 900 or height <= 520
                assert page.locator("#sidebar").is_visible() != compact
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                for selector in ("#sideBtn","#gwPills","#messages","#input","#send"):
                    check_frame(page, selector)
                assert page.locator("#messages").bounding_box()["height"] >= 60
                if width <= 1100 or height <= 520:
                    for selector in ("#gwPills .pill:last-child","#perm","#projectBtn"):
                        page.locator(selector).scroll_into_view_if_needed()
                        check_frame(page, selector)
                    check_frame(page, "#send")
                if compact:
                    page.locator("#sideBtn").click()
                    check_frame(page,"#sidebar")
                    assert page.evaluate("document.querySelector('main').inert")
                    page.locator("#drawerClose").click()
                    assert not page.locator("#sidebar").is_visible()
                    page.locator("#sideBtn").click()
                    page.locator("#newChat").click()
                    assert not page.locator("#sidebar").is_visible()
                print(lang,width,height,"passed",flush=True)
            button = page.locator("#projectBtn")
            page.evaluate("S.conv=42")
            button.click()
            page.wait_for_timeout(100)
            assert page.evaluate("S.conv") == 42 and "Workspace" in button.inner_text()
            button.click()
            page.wait_for_function("S.project === 'My files' && S.conv === null")
            assert "My files" in button.inner_text()
            page.reload()
            page.wait_for_function("document.querySelector('#projectBtn').textContent.includes('My files')")
            print(lang,"folder selection, cancellation and restart passed",flush=True)
            page.close()
        browser.close()
finally:
    server.shutdown()
