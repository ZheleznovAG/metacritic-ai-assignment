import argparse
import json
import os
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description="Local live UI audit; excluded from offline CI.")
parser.add_argument("--base", default="http://127.0.0.1:18081")
parser.add_argument("--output", type=Path, default=Path(".artifacts/ui-opt-03"))
parser.add_argument("--tools", type=Path, default=Path(".artifacts/ui-opt-03-tools"))
args = parser.parse_args()
OUT = args.output
OUT.mkdir(parents=True, exist_ok=True)
BASE = args.base.rstrip("/")
records = []
with sync_playwright() as p:
    executable = p.chromium.executable_path
    browser = p.chromium.launch()
    for color in ("light", "dark"):
        for width in (1280, 390, 320):
            context = browser.new_context(
                viewport={"width": width, "height": 900}, color_scheme=color
            )
            page = context.new_page()
            page.goto(BASE)
            detail = page.locator(".game-list__item a").first.get_attribute("href")
            for name, path in (("catalog", "/"), ("detail", detail), ("monitoring", "/ops/")):
                response = page.goto(BASE + path)
                page.add_script_tag(path=str(args.tools / "node_modules/axe-core/axe.min.js"))
                result = page.evaluate(
                    "async () => { const r = await axe.run(); return {violations:r.violations, incomplete:r.incomplete, passes:r.passes.map(x=>x.id)}; }"
                )
                metrics = page.evaluate(
                    """() => ({elements:document.querySelectorAll('*').length, cards:document.querySelectorAll('.game-list__item').length, overflow:document.documentElement.scrollWidth>innerWidth, images:[...document.images].map(i=>({src:i.src,width:i.width,height:i.height,naturalWidth:i.naturalWidth,loading:i.loading,priority:i.fetchPriority,decode:i.decoding,ratio:getComputedStyle(i).aspectRatio})), resources:performance.getEntriesByType('resource').map(r=>({name:r.name,bytes:r.transferSize,duration:r.duration}))})"""
                )
                records.append(
                    {
                        "page": name,
                        "path": path,
                        "width": width,
                        "color": color,
                        "cache": response.headers.get("cache-control"),
                        "axe": result,
                        "metrics": metrics,
                    }
                )
                print(
                    name,
                    width,
                    color,
                    "violations",
                    [(v["id"], v["impact"]) for v in result["violations"]],
                    flush=True,
                )
            if color == "light" and width == 1280:
                page.evaluate(
                    """() => { const b=document.createElement('button'); b.id='audit-negative'; b.style='position:fixed;top:0;left:0'; document.body.append(b); }"""
                )
                negative = page.evaluate(
                    "async () => (await axe.run({runOnly:['button-name']})).violations"
                )
                assert any(v["id"] == "button-name" for v in negative)
                OUT.joinpath("negative-control.json").write_text(
                    json.dumps(negative, indent=2), encoding="utf-8"
                )
                page.locator("#audit-negative").evaluate("e => e.remove()")
            context.close()
    browser.close()
OUT.joinpath("browser.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
env = dict(os.environ, CHROME_PATH=executable)
cli = str(args.tools / "node_modules/lighthouse/cli/index.js")
for form in ("desktop", "mobile"):
    for name, path in (("catalog", "/"), ("detail", detail)):
        cmd = [
            "node",
            cli,
            BASE + path,
            "--chrome-flags=--headless --no-sandbox",
            "--only-categories=performance,accessibility,best-practices",
            "--output=json",
            f"--output-path={OUT / (form + '-' + name + '.json')}",
            "--quiet",
        ]
        if form == "desktop":
            cmd += [
                "--preset=desktop",
                "--screenEmulation.width=1280",
                "--screenEmulation.height=900",
            ]
        else:
            cmd += ["--screenEmulation.width=390", "--screenEmulation.height=900"]
        print("Lighthouse", form, name, flush=True)
        subprocess.run(cmd, env=env, check=True)
