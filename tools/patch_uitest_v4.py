import sys, os, shutil
root = sys.argv[1]; p = os.path.join(root, "tools", "ui_test.py")
os.makedirs(os.path.join(root, "backup-v4", "tools"), exist_ok=True)
d = os.path.join(root, "backup-v4", "tools", "ui_test.py")
if not os.path.exists(d): shutil.copy2(p, d)
s = open(p, encoding="utf-8").read()
anchor = '        elif step == "vram":'
assert s.count(anchor) == 1
add = '''        elif step.startswith("eng:"):
            # eng:<key>:on|off - the engine model's own toggle in the Models panel (switching stops the other one)
            _, key, want = step.split(":"); want = want == "on"
            c.go(A.url, 3); c.js("document.querySelector('#openModels').click()"); time.sleep(3)
            sel = f"[data-eng=\\\\"{key}\\\\"]"
            if c.js(f"document.querySelector('{sel}').classList.contains('on')") != want:
                c.js(f"document.querySelector('{sel}').click()"); time.sleep(1)
                print("  confirm:", c.js("document.querySelector('#modal').innerText.replace(/\\\\s+/g,' ').slice(0,260)"))
                c.shot(f"v4-eng-{key}-{'on' if want else 'off'}-confirm"); c.js("document.querySelector('#modalYes').click()")
                time.sleep(5); c.shot(f"v4-eng-{key}-progress"); print("  job:", wait_job(c, 300)); time.sleep(4)
            c.shot(f"v4-eng-{key}-{'on' if want else 'off'}-done")
            print("  engines:", c.js("fetch('/api/models').then(r=>r.json()).then(j=>j.engines.map(e=>e.key+'='+e.online).join(' ')+' lm='+j.lmstudio.models.filter(m=>m.loaded).map(m=>m.key).join('+'))"))
            print("  picker:", c.js("document.querySelector('#modelName').innerText+' / '+document.querySelector('#modelSub').innerText"))
            print("  errors:", c.errors() or "none"); c.js("document.querySelector('#sheetScrim').click()")
        elif step.startswith("img:"):
            # img:<model id>:<png path> - attach an image through the real file input and ask about it (effort off)
            _, mid, img = step.split(":", 2)
            c.go(A.url, 3); c.js("document.querySelector('#newChat').click()"); time.sleep(0.5)
            print("  model:", use_model(c, "engine", mid), "| effort:", effort(c, "off"))
            doc = c.call("DOM.getDocument")["root"]["nodeId"]; nid = c.call("DOM.querySelector", nodeId=doc, selector="#fileInput")["nodeId"]
            c.call("DOM.setFileInputFiles", nodeId=nid, files=[img]); time.sleep(1.5)
            print("  attached:", c.js("document.querySelectorAll('#attachRow img, #attachRow .att').length"))
            r = ask(c, "Which region has the tallest bar in this chart, and what is its value? One short sentence.", (f"v4-img-mid", 2.0))
            print("  reply:", json.dumps(r, ensure_ascii=False)); c.shot("v4-img-done")
            print("  errors:", c.errors() or "none")
'''
s = s.replace(anchor, add + anchor)
open(p, "w", encoding="utf-8", newline="").write(s); print("ui_test patched")
