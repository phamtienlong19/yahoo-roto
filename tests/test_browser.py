"""The page in a real (headless) Chrome, on the generated 18-team league: it renders without errors, the snapshot toggle, sort, crown, opponent line and arrow keys work, and a
saved image has exactly the size of the command-line image of the same board. Skipped when Chrome is not installed (set ROTO_NO_BROWSER=1 to skip on purpose)."""
import functools
import http.server
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import golden  # noqa: E402
import yahoo_roto as yr  # noqa: E402

HARNESS = r"""<!doctype html><meta charset=utf-8><body><pre id=out>pending</pre><script>
var R={},errors=[];
function load(q){return new Promise(function(res){var f=document.createElement('iframe');f.style.cssText='width:1100px;height:900px;border:0';f.src='index.html?'+q;
 f.onload=function(){var w=f.contentWindow;w.addEventListener('error',function(e){errors.push(e.message)});setTimeout(function(){res({f:f,w:w,d:w.document})},700);};document.body.appendChild(f);});}
function txt(e){return e?e.textContent.trim():null}
function key(p,el,k){el.dispatchEvent(new p.w.KeyboardEvent('keydown',{key:k,bubbles:true}));}
function save(p,name){return new Promise(function(res,rej){var t=setTimeout(function(){rej(new Error('export timed out'))},45000);
 p.w.HTMLAnchorElement.prototype.click=function(){var a=this;p.w.fetch(a.href).then(function(r){return r.blob()}).then(function(b){return fetch('/post/'+name,{method:'POST',body:b})}).then(function(){clearTimeout(t);res()});};
 p.d.getElementById('save').click();});}
(async function(){try{
 var p=await load('season=1&board=boom');
 R.ready=p.d.body.getAttribute('data-ready');R.h1a=txt(p.d.querySelector('h1'));R.snapButtons=p.d.querySelectorAll('.snapbar button').length;
 p.d.querySelectorAll('.snapbar button')[1].click();R.h1b=txt(p.d.querySelector('h1'));
 p=await load('week=4&view=stats');
 var heads=[].slice.call(p.d.querySelectorAll('.st thead tr:last-child th')),ix=heads.map(txt).indexOf('PTS');
 R.crowns=p.d.querySelectorAll('.st th.team .crown').length;R.vs=p.d.querySelectorAll('.st th.team .vs').length;R.scoreClasses=[].slice.call(p.d.querySelectorAll('td.score')).map(function(e){return e.className.replace('score ','')});
 heads[ix].click();var col=[].slice.call(p.d.querySelectorAll('.st tbody tr')).map(function(r){return parseFloat(r.cells[ix].textContent)});R.sortDesc=col.every(function(v,i){return i===0||col[i-1]>=v});
 heads[ix].click();col=[].slice.call(p.d.querySelectorAll('.st tbody tr')).map(function(r){return parseFloat(r.cells[ix].textContent)});R.sortAsc=col.every(function(v,i){return i===0||col[i-1]<=v});
 p=await load('week=3&view=roto');
 var cur=function(){return txt(p.d.querySelector('.strip [aria-current=true]'))};R.week0=cur();key(p,p.d.body,'ArrowLeft');R.week1=cur();
 key(p,p.d.querySelector('.tscroll'),'ArrowRight');R.week2=cur();
 p=await load('week=3&view=allplay');
 var mh=[].slice.call(p.d.querySelectorAll('.mx thead tr th')),last=mh[mh.length-1];last.click();
 var pct=[].slice.call(p.d.querySelectorAll('.mx tbody tr')).map(function(r){return parseFloat(r.cells[r.cells.length-1].textContent)});R.matrixSorted=pct.every(function(v,i){return i===0||pct[i-1]>=v});
 R.legendFull=!!p.d.querySelector('.legend.full');R.meline=!!p.d.querySelector('.meline');
 p=await load('week=3&view=stats');await save(p,'stats.png');
 p=await load('season=1&board=power');await save(p,'power.png');
 R.errors=errors;
}catch(e){R.fatal=String(e&&e.message||e);R.errors=errors}
document.getElementById('out').textContent=JSON.stringify(R);document.title='done';})();
</script>"""


def png_size(data):
    return struct.unpack(">II", data[16:24])


@unittest.skipIf(os.environ.get("ROTO_NO_BROWSER") == "1" or not yr.find_chrome(), "Chrome not installed (or ROTO_NO_BROWSER=1)")
class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.site = os.path.join(cls.tmp.name, "site")
        yr.write_html(golden.build_report(18, 4), cls.site)
        with open(os.path.join(cls.site, "t.html"), "w", encoding="utf-8") as f:
            f.write(HARNESS)
        cls.posted = {}
        posted = cls.posted

        class Handler(http.server.SimpleHTTPRequestHandler):
            def do_POST(self):
                posted[self.path.rsplit("/", 1)[-1]] = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                pass
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=cls.site))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        dom = subprocess.run([yr.find_chrome(), "--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=90000", "--window-size=1100,900", "--dump-dom",
                              "http://127.0.0.1:%d/t.html" % cls.server.server_address[1]], capture_output=True, text=True, timeout=240).stdout
        m = re.search(r'<pre id="out">(.*?)</pre>', dom, re.S)
        cls.R = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")) if m and m.group(1) != "pending" else {"fatal": "no result"}

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def test_the_page_runs_without_errors(self):
        self.assertNotIn("fatal", self.R, self.R)
        self.assertEqual(self.R["errors"], [])
        self.assertEqual(self.R["ready"], "1")

    def test_the_snapshot_toggle_switches_between_final_and_live_weeks(self):
        self.assertEqual(self.R["snapButtons"], 2)
        self.assertIn("Weeks 1-3", self.R["h1a"])
        self.assertIn("Weeks 1-4", self.R["h1b"])

    def test_the_crown_the_opponent_line_and_the_score_colours(self):
        self.assertEqual(self.R["crowns"], 1)
        self.assertEqual(self.R["vs"], 18)
        self.assertTrue(set(self.R["scoreClasses"]) <= {"green-strong", "red-strong", "mid"})
        self.assertIn("green-strong", self.R["scoreClasses"])

    def test_clicking_a_header_sorts_both_ways_and_the_matrix_sorts_by_win_percent(self):
        self.assertTrue(self.R["sortDesc"])
        self.assertTrue(self.R["sortAsc"])
        self.assertTrue(self.R["matrixSorted"])
        self.assertTrue(self.R["legendFull"] and self.R["meline"] in (True, False))

    def test_arrow_keys_change_the_week_except_inside_a_table(self):
        self.assertEqual((self.R["week0"], self.R["week1"], self.R["week2"]), ("W3", "W2", "W2"))

    def test_a_saved_image_has_exactly_the_size_of_the_command_line_image(self):
        index = os.path.join(self.site, "index.html")
        out = os.path.join(self.tmp.name, "cli")
        os.makedirs(out)
        yr.write_images(index, out, week=3)
        yr.write_images(index, out, season=True)
        self.assertIn("stats.png", self.posted)
        self.assertIn("power.png", self.posted)
        with open(os.path.join(out, "stats.png"), "rb") as f:
            self.assertEqual(png_size(self.posted["stats.png"]), png_size(f.read()))
        with open(os.path.join(out, "season-power.png"), "rb") as f:
            self.assertEqual(png_size(self.posted["power.png"]), png_size(f.read()))
        self.assertTrue(self.posted["stats.png"].startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
