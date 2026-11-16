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
function load(q,base){return new Promise(function(res){var f=document.createElement('iframe');f.style.cssText='width:1100px;height:900px;border:0';f.src=(base||'')+'index.html?'+q;
 f.onload=function(){var w=f.contentWindow;w.addEventListener('error',function(e){errors.push(e.message)});setTimeout(function(){res({f:f,w:w,d:w.document})},700);};document.body.appendChild(f);});}
function txt(e){return e?e.textContent.trim():null}
function key(p,el,k){el.dispatchEvent(new p.w.KeyboardEvent('keydown',{key:k,bubbles:true}));}
function save(p,name){return new Promise(function(res,rej){var t=setTimeout(function(){var ts=p.d.querySelector('.toast');rej(new Error('export timed out'+(ts?': '+ts.textContent:' (no error toast)')))},120000);
 p.w.HTMLAnchorElement.prototype.click=function(){var a=this;p.w.fetch(a.href).then(function(r){return r.blob()}).then(function(b){return fetch('/post/'+name,{method:'POST',body:b})}).then(function(){clearTimeout(t);res()});};
 p.d.getElementById('save').click();});}
(async function(){try{
 var p=await load('season=1&board=boom');
 R.ready=p.d.body.getAttribute('data-ready');R.h1a=txt(p.d.querySelector('h1'));R.snapButtons=p.d.querySelectorAll('#snapbar button').length;
 p.d.querySelectorAll('#snapbar button')[1].click();R.h1b=txt(p.d.querySelector('h1'));
 var sf=p.d.querySelector('.snapbar select[aria-label="From week"]');sf.value='2';sf.dispatchEvent(new p.w.Event('change'));R.h1c=txt(p.d.querySelector('h1'));R.url=p.w.location.search;
 R.activeChips=p.d.querySelectorAll('#snapbar button.on').length;
 p=await load('season=1&board=luckweeks&range=2-3');R.lwH1=txt(p.d.querySelector('h1'));R.lwLens=p.d.querySelectorAll('#lensbar button.on').length;R.lwCols=p.d.querySelectorAll('.tscroll .st thead tr:last-child th').length;R.lwRows=p.d.querySelectorAll('.st tbody tr').length;
 p=await load('week=4&view=matchups');R.muRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.muPairs=p.d.querySelectorAll('.tscroll .st tbody tr.pe').length;R.muSortable=p.d.querySelectorAll('.tscroll .st th.sortable').length;
 R.muLuck=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).map(function(r){return parseFloat(r.cells[r.cells.length-1].textContent.replace('\u2212','-'))}).reduce(function(a,b){return a+b},0);
 p=await load('season=1&board=luck&lens=catweek&range=2-3');R.cwH1=txt(p.d.querySelector('h1'));R.cwCols=p.d.querySelectorAll('.tscroll .st thead tr:last-child th').length;R.cwCells=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr:first-child td')).map(txt);
 p=await load('season=1&board=luck&lens=catweek&cat=PTS&range=2-3');R.cwPickH1=txt(p.d.querySelector('h1'));R.cwPickCells=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr:first-child td')).map(txt);
 p=await load('season=1&board=catluck');R.clH1=txt(p.d.querySelector('h1'));R.clHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);
 p=await load('season=1&board=boom','old/');R.oldNote=txt(p.d.querySelector('.snapbar .rnote'));R.oldSelects=p.d.querySelectorAll('.snapbar select').length;R.oldChips=p.d.querySelectorAll('#snapbar .seg button').length;
 p=await load('season=1&board=luck&range=4-4');R.oneWeek=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).map(function(r){return [r.cells[1].className.replace('cat ',''),r.cells[2].className.replace('total sep ','')]});
 R.alias={};
 for(var b of ['roto','totals','weekly','power','matrix','allplay','real','luck','luckweeks','catluck','matchlog','kings','boom','standings','records']){
  p=await load('season=1&board='+b);R.alias[b]=[txt(p.d.querySelector('h1')),txt(p.d.querySelector('#nav .active')),txt(p.d.querySelector('#lensbar button.on')),p.w.location.search];}
 p=await load('season=1&board=real');R.tabs=[].slice.call(p.d.querySelectorAll('#nav button')).map(txt);R.lenses=[].slice.call(p.d.querySelectorAll('#lensbar button')).map(txt);R.realHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);
 p=await load('season=1&board=standings&lens=odds');R.odH1=txt(p.d.querySelector('h1'));R.odHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.odRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.odBars=p.d.querySelectorAll('.tscroll .st tbody tr:first-child .hb i').length;R.odIn=p.d.querySelectorAll('.tscroll .st tbody tr:first-child .hb i.po').length;R.odRange=p.d.querySelectorAll('#snapbar button').length;R.odPct=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td.total'));

 p=await load('season=1&board=luck&lens=expected&range=1-3');R.exH1=txt(p.d.querySelector('h1'));R.exHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.exRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;
 p=await load('season=1&board=luck&lens=sos&range=1-3');R.sosH1=txt(p.d.querySelector('h1'));R.sosHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.sosRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;
 p=await load('season=1&board=matchlog&range=1-3');R.mlRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.mlH1=txt(p.d.querySelector('h1'));
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
        yr.write_html(golden.build_report(18, 4, regular=10, divisions=True), cls.site)
        old = golden.build_report(18, 4, regular=10, divisions=True)                                  # a report from before the week ranges: no made/attempts in the week views
        for v in old["views"].values():
            for t in v["teams"].values():
                t.pop("raw", None)
        yr.write_html(old, os.path.join(cls.site, "old"))
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
        dom = subprocess.run([yr.find_chrome(), "--headless", "--disable-gpu", "--no-sandbox", "--virtual-time-budget=300000", "--window-size=1100,900", "--dump-dom",
                              "http://127.0.0.1:%d/t.html" % cls.server.server_address[1]], capture_output=True, text=True, timeout=360).stdout
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

    def test_the_week_range_picks_any_weeks_and_lives_in_the_link(self):
        self.assertIn("Weeks 2-4", self.R["h1c"])
        self.assertIn("range=2-4", self.R["url"])
        self.assertEqual(self.R["activeChips"], 0)                       # a custom range is neither of the two preset chips

    def test_matchup_view_lists_each_matchup_as_a_pair_of_rows_with_plain_numbers(self):
        self.assertEqual((self.R["muRows"], self.R["muPairs"]), (18, 9))
        self.assertEqual(self.R["muSortable"], 0)                         # pairs must stay together
        self.assertAlmostEqual(self.R["muLuck"], 0, delta=0.2)            # luck is zero-sum over a week (up to the 2-decimal rounding of 18 cells)

    def test_category_luck_by_week_and_the_old_category_luck_link(self):
        self.assertIn("Category Luck by Week", self.R["cwH1"])
        self.assertEqual(self.R["cwCols"], 1 + 2 + 3)
        self.assertNotEqual(self.R["cwCells"][:2], self.R["cwPickCells"][:2])            # picking PTS changes the numbers
        self.assertIn("· PTS", self.R["cwPickH1"])
        self.assertIn("Category Luck", self.R["clH1"])                                   # board=catluck still opens the by-category view
        self.assertIn("Matchup luck", self.R["clHeads"])
        self.assertIn("PTS", self.R["clHeads"])

    def test_an_older_report_without_made_attempts_says_why_custom_ranges_are_missing(self):
        self.assertIn("after the next data refresh", self.R["oldNote"])
        self.assertEqual((self.R["oldSelects"], self.R["oldChips"]), (0, 2))              # the two preset ranges still work

    def test_a_one_week_range_colours_the_total_like_the_week_cell(self):
        self.assertEqual(len(self.R["oneWeek"]), 18)
        for week_cell, total_cell in self.R["oneWeek"]:
            self.assertEqual(week_cell, total_cell)

    def test_every_old_board_link_opens_the_same_table_inside_its_tab(self):
        want = {"roto": ("Roto Rank", "Standings", "Season Roto"), "totals": ("Stats", "Standings", "Raw Totals"), "weekly": ("Weekly Roto Points", "Standings", "Weekly Roto Points"),
                "power": ("Power Rank", "Standings", "Power Rank"), "matrix": ("All-Play Matrix", "All-Play", "Matrix"), "allplay": ("Season All-Play", "All-Play", "Season All-Play"),
                "real": ("Real Record & Luck", "Luck", "Summary"), "luck": ("Luck by Week", "Luck", "By week"), "luckweeks": ("Luck by Week", "Luck", "By week"),
                "catluck": ("Category Luck", "Luck", "By category"), "matchlog": ("Matchup Log", "Luck", "Matchup Log"), "kings": ("Category Kings", "Records", "Category Kings"),
                "boom": ("Boom / Bust", "Records", "Boom / Bust"), "standings": ("Roto Rank", "Standings", "Season Roto"), "records": ("Category Kings", "Records", "Category Kings")}
        for board, (title, tab, lens) in want.items():
            h1, active_tab, active_lens, search = self.R["alias"][board]
            self.assertIn(title, h1, board)
            self.assertEqual((active_tab, active_lens), (tab, lens), board)
            self.assertIn("lens=", search, board)                                   # the address is rewritten to the new form (board=<tab>&lens=<view>)

    def test_four_tabs_with_the_views_of_the_open_tab_under_them(self):
        self.assertEqual(self.R["tabs"], ["Standings", "All-Play", "Luck", "Records"])
        self.assertEqual(self.R["lenses"], ["Summary", "Expected standings", "Schedule", "By week", "By week \u00b7 categories", "By category", "Matchup Log"])
        self.assertIn("Cat luck", self.R["realHeads"])                               # real record and luck, with category luck folded in

    def test_playoff_odds_view(self):
        self.assertIn("Playoff Odds", self.R["odH1"])
        self.assertEqual(self.R["odHeads"], ["Team", "Div", "Playoffs", "Top seed", "Proj. rank", "Cat pts", "Finishing place"])
        self.assertEqual((self.R["odRows"], self.R["odBars"], self.R["odIn"]), (18, 18, 6))        # a bar per place, the six playoff places in green
        self.assertEqual(self.R["odRange"], 0)                                                       # the week range does not apply to it
        self.assertRegex(self.R["odPct"], r"^(>99|<1|\d+)%$")

    def test_expected_standings_and_strength_of_schedule_views(self):
        self.assertIn("Expected Standings", self.R["exH1"])
        self.assertEqual(self.R["exHeads"][:4], ["Team", "Exp. rank", "Real rank", "Diff"])
        self.assertEqual(self.R["exRows"], 18)
        self.assertIn("Strength of Schedule", self.R["sosH1"])
        self.assertEqual(self.R["sosHeads"], ["Team", "SOS", "vs avg", "Rank", "Schedule luck", "Result luck", "Luck"])
        self.assertEqual(self.R["sosRows"], 18)

    def test_matchup_log_has_a_row_per_team_and_week(self):
        self.assertEqual(self.R["mlRows"], 3 * 18)
        self.assertIn("Weeks 1-3", self.R["mlH1"])

    def test_luck_by_week_has_a_column_per_week_in_the_range(self):
        self.assertIn("Weeks 2-3", self.R["lwH1"])
        self.assertEqual((self.R["lwCols"], self.R["lwRows"]), (1 + 2 + 3, 18))      # team, two weeks, Matchup luck, Cat luck, Rank
        self.assertEqual(self.R["lwLens"], 1)

    def test_the_crown_the_opponent_line_and_the_score_colours(self):
        self.assertEqual(self.R["crowns"], 1)
        self.assertEqual(self.R["vs"], 18)
        shades = {"dark-green", "green", "light-green", "white", "light-red", "red", "dark-red", "mid"}      # the All-Play Matrix margin shades
        self.assertTrue(set(self.R["scoreClasses"]) <= shades, self.R["scoreClasses"])
        self.assertGreaterEqual(len(set(self.R["scoreClasses"])), 3)                                     # margins of different size get different shades
        self.assertTrue({"light-green", "green", "dark-green"} & set(self.R["scoreClasses"]))

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
