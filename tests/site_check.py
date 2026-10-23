"""Site check: every page loads without a script error, fits a phone screen, and every internal link points at
a file that exists. Shared by the three LDB sites; run on every push by .github/workflows/site-check.yml.

  python3 tests/site_check.py --prefix /finance/        (from the repo root; '/' for the main site)

Exit code 1 lists every failure. Large model downloads (Hugging Face, WebLLM) are blocked during the browser pass:
the check is that pages work and degrade gracefully, not that a 1 GB model downloads.
"""
import argparse
import html
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from urllib.parse import urlparse, unquote

HOST = 'ldiazbusquets.github.io'
BLOCK = re.compile(r'huggingface\.co|hf\.co|cdn-lfs|web-llm|@huggingface/transformers|onnxruntime-web|googletagmanager')
SKIP_PAGES = {'404.html'}   # GitHub's not-found page uses absolute links to the live site
SIBLINGS = ('finance/', 'lab/')   # from the main site, these relative links lead to the other two repos
OPTIONAL = {'excel-guide.html'}   # linked only when the file exists (the page checks first)


def pages(root):
    out = []
    for d, _, fs in os.walk(root):
        if any(p in d for p in ('.git', 'node_modules', '_source', 'tests')):
            continue
        for f in fs:
            if f.endswith('.html'):
                out.append(os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/'))
    return sorted(out)


def static_links(root, prefix):
    """every href/src in the HTML that should resolve inside this repo"""
    errs, warn, n = [], [], 0
    for page in pages(root):
        src = open(os.path.join(root, page), encoding='utf-8', errors='replace').read()
        src_wo_scripts = re.sub(r'<script\b[^>]*>.*?</script>', '', src, flags=re.S)
        src_wo_scripts = re.sub(r'<base [^>]*>', '', src_wo_scripts)
        ids = set(re.findall(r'\bid="([^"]+)"', src)) | set(re.findall(r'\bname="([^"]+)"', src))
        bm = re.search(r'<base href="([^"]*)"', src)
        base_dir = os.path.normpath(os.path.join(os.path.dirname(page), bm.group(1))).replace(os.sep, '/') if bm else os.path.dirname(page)
        if base_dir == '.':
            base_dir = ''
        for attr, url in re.findall(r'\b(href|src)="([^"]*)"', src_wo_scripts):
            url = html.unescape(url).strip()
            if not url or url.startswith(('mailto:', 'tel:', 'javascript:', 'data:', 'blob:')):
                continue
            u = urlparse(url)
            if u.scheme in ('http', 'https'):
                if u.netloc != HOST or not u.path.startswith(prefix):
                    continue                      # another site: not ours to check here
                path = u.path[len(prefix):]
            elif url.startswith('//'):
                continue
            elif u.path.startswith('/'):
                if not u.path.startswith(prefix):
                    continue                      # one of the sibling sites
                path = u.path[len(prefix):]
            else:
                if not u.path and bm:
                    errs.append(f'{page}: href="{url}" points at the <base> folder, not this page'); continue
                path = os.path.normpath(os.path.join(base_dir, u.path)).replace(os.sep, '/') if u.path else page
            path = unquote(path)
            if prefix == '/' and (path + '/').startswith(SIBLINGS) or path in OPTIONAL:
                continue
            n += 1
            full = os.path.join(root, path)
            if path in ('', '.') or os.path.isdir(full):
                full = os.path.join(full, 'index.html')
            if not os.path.exists(full):
                errs.append(f'{page}: {attr}="{url}" -> missing {path or "index.html"}')
                continue
            if u.fragment and full.endswith('.html'):
                tids = ids if os.path.abspath(full) == os.path.abspath(os.path.join(root, page)) else \
                    set(re.findall(r'\b(?:id|name)="([^"]+)"', open(full, encoding='utf-8', errors='replace').read()))
                if u.fragment not in tids:
                    warn.append(f'{page}: #{u.fragment} not found in {path} (may be created by a script)')
    return n, errs, warn


def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def serve(root, prefix):
    """serve the repo at its live path (e.g. /finance/) so absolute links and fetches behave as on GitHub Pages"""
    tmp = tempfile.mkdtemp()
    mount = os.path.join(tmp, prefix.strip('/')) if prefix.strip('/') else tmp
    if prefix.strip('/'):
        os.symlink(os.path.abspath(root), mount)
        base = tmp
    else:
        base = os.path.abspath(root)
    port = free_port()
    httpd = ThreadingHTTPServer(('127.0.0.1', port), partial(QuietHandler, directory=base))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port, tmp


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def browser(root, prefix, widths=(390, 1280)):
    from playwright.sync_api import sync_playwright
    httpd, port, tmp = serve(root, prefix)
    errs = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            for w in widths:
                ctx = b.new_context(viewport={'width': w, 'height': 900}, is_mobile=w < 600, has_touch=w < 600)
                ctx.route(BLOCK, lambda r: r.abort())
                pg = ctx.new_page()
                bad = []
                pg.on('pageerror', lambda e: bad.append(str(e).split('\n')[0][:160]))
                for page in pages(root):
                    if page in SKIP_PAGES or 'http-equiv="refresh"' in open(os.path.join(root, page), encoding='utf-8', errors='replace').read():
                        continue      # redirect stubs leave for the live site
                    bad.clear()
                    url = f'http://127.0.0.1:{port}{prefix}{page}'
                    try:
                        r = pg.goto(url, wait_until='load', timeout=30000)
                        pg.wait_for_timeout(700)
                    except Exception as e:
                        errs.append(f'{page} @{w}px: did not load ({str(e)[:100]})'); continue
                    if r is None or r.status >= 400:
                        errs.append(f'{page} @{w}px: HTTP {r.status if r else "?"}')
                    for e in bad:
                        if 'Failed to fetch' in e or 'NetworkError' in e or 'net::ERR' in e:
                            continue      # a blocked download; the page must handle it, and the error is reported in-page
                        errs.append(f'{page} @{w}px: script error: {e}')
                    sw = pg.evaluate('document.documentElement.scrollWidth')
                    if sw > w + 1:
                        errs.append(f'{page} @{w}px: page is {sw}px wide (scrolls sideways)')
                ctx.close()
            b.close()
    finally:
        httpd.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    return errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='.')
    ap.add_argument('--prefix', default='/')
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    prefix = '/' + a.prefix.strip('/') + '/' if a.prefix.strip('/') else '/'
    n, errs, warn = static_links(a.root, prefix)
    print(f'links: {n} internal links checked, {len(errs)} broken, {len(warn)} anchors only a script could create')
    for w in warn[:20]:
        print('  note', w)
    if not a.no_browser:
        t = time.time()
        b = browser(a.root, prefix)
        print(f'browser: {len(pages(a.root))} pages at phone and desktop width in {time.time() - t:.0f}s, {len(b)} problems')
        errs += b
    for e in errs:
        print('  FAIL', e)
    sys.exit(1 if errs else 0)


if __name__ == '__main__':
    main()
