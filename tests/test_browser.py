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
import test_current_week  # noqa: E402
import yahoo_roto as yr  # noqa: E402

HARNESS = r"""<!doctype html><meta charset=utf-8><body><pre id=out>pending</pre><script>
var R={},errors=[];
var COLOURS=[['board=real',['Luck','Places vs expected']],['board=luck&lens=summary&basis=cats',['Category luck','Places vs expected']],['board=luck&lens=week',['Wk 2','Luck']],['board=luck&lens=cat',['PTS','TO','Luck']],
 ['board=outlook&lens=sos',['SOS','Rank']],['board=outlook&lens=odds',['Playoffs']],['board=weekly',['Points','Rank']],['board=allplay',['Win%','Rank']],['board=power',['Season Roto','Weekly Roto','Season All-Play','Real Record','Power']],['board=roto',['Total']],
 ['board=matchlog',['Luck']],['board=performance&lens=form',['Win%']],];
var PLAIN=[['board=real',['Record','Wins','Expected wins','Rank','Expected rank']],['board=luck&lens=cat',['Won','Expected','Rank']],['board=outlook&lens=sos',["Opponents' record"]],['board=outlook&lens=odds',['Top seed','Projected rank','Odds trend']],
 ['board=weekly',['Per week']],['board=allplay',['W-L-T']],['board=matchlog',['All-play Win%',"Opponent's Win%"]],['board=roto',['Rank']],['board=performance&lens=form',['Last 3','Season Win%','Stats said']],['board=performance&lens=split',['Vs strong','Vs weak']]];
var COPYQ=['season=1&board=roto','season=1&board=totals','season=1&board=matrix','season=1&board=weekly','season=1&board=allplay','season=1&board=real','season=1&board=luck&lens=summary&basis=cats','season=1&board=luck&lens=week','season=1&board=luck&lens=week&basis=cats','season=1&board=luck&lens=cat',
 'season=1&board=matchlog','season=1&board=outlook&lens=sos','season=1&board=outlook&lens=odds','season=1&board=kings','season=1&board=performance&lens=form','season=1&board=performance&lens=split','season=1&board=performance&lens=trends','season=1&board=power','week=3&view=roto','week=3&view=stats','week=3&view=allplay','week=3&view=matchups'];
var FITS=['board=roto','board=totals','board=matrix','board=weekly','board=allplay','board=real','board=luck&lens=summary&basis=cats','board=luck&lens=week','board=luck&lens=week&basis=cats','board=luck&lens=cat','board=outlook&lens=sos','board=outlook&lens=sos&basis=cats','board=outlook&lens=odds','board=kings','board=performance&lens=form','board=performance&lens=split','board=performance&lens=trends','board=power'];
function load(q,base,width){return new Promise(function(res){var f=document.createElement('iframe');f.style.cssText='width:'+(width||1100)+'px;height:900px;border:0';f.src=(base||'')+'index.html?'+q;
 f.onload=function(){var w=f.contentWindow;w.addEventListener('error',function(e){errors.push(e.message)});setTimeout(function(){res({f:f,w:w,d:w.document})},700);};document.body.appendChild(f);});}
function txt(e){return e?e.textContent.trim():null}
function key(p,el,k){el.dispatchEvent(new p.w.KeyboardEvent('keydown',{key:k,bubbles:true}));}
function save(p,name){return new Promise(function(res,rej){var t=setTimeout(function(){var ts=p.d.querySelector('.toast');rej(new Error('export timed out'+(ts?': '+ts.textContent:' (no error toast)')))},120000);
 p.w.HTMLAnchorElement.prototype.click=function(){var a=this;p.w.fetch(a.href).then(function(r){return r.blob()}).then(function(b){return fetch('/post/'+name,{method:'POST',body:b})}).then(function(){clearTimeout(t);res()});};
 p.d.getElementById('save').click();});}
(async function(){try{
 var p=await load('season=1&board=weekly');
 R.ready=p.d.body.getAttribute('data-ready');R.h1a=txt(p.d.querySelector('h1'));R.snapButtons=p.d.querySelectorAll('#snapbar button').length;
 p.d.querySelectorAll('#snapbar button')[1].click();R.h1b=txt(p.d.querySelector('h1'));
 var sf=p.d.querySelector('.snapbar select[aria-label="From week"]');sf.value='2';sf.dispatchEvent(new p.w.Event('change'));R.h1c=txt(p.d.querySelector('h1'));R.url=p.w.location.search;
 R.activeChips=p.d.querySelectorAll('#snapbar button.on').length;
 p=await load('season=1&board=luckweeks&range=2-3');R.lwH1=txt(p.d.querySelector('h1'));R.lwLens=p.d.querySelectorAll('#lensbar .seg:first-child button.on').length;R.lwCols=p.d.querySelectorAll('.tscroll .st thead tr:last-child th').length;R.lwRows=p.d.querySelectorAll('.st tbody tr').length;
 p=await load('week=4&view=matchups');R.muRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.muPairs=p.d.querySelectorAll('.tscroll .st tbody tr.pe').length;R.muSortable=p.d.querySelectorAll('.tscroll .st th.sortable').length;
 R.muLuck=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).map(function(r){return parseFloat(r.cells[r.cells.length-1].textContent.replace('\u2212','-'))}).reduce(function(a,b){return a+b},0);
 p=await load('season=1&board=luck&lens=catweek&range=2-3');R.cwUrl=p.w.location.search;R.cwH1=txt(p.d.querySelector('h1'));R.cwCols=p.d.querySelectorAll('.tscroll .st thead tr:last-child th').length;R.cwBasis=txt(p.d.querySelector('#lensbar .seg:nth-child(2) button.on'));R.cwCells=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr:first-child td')).map(txt);
 p=await load('season=1&board=luck&lens=catweek&cat=PTS&range=2-3');R.cwPickH1=txt(p.d.querySelector('h1'));R.cwPickCells=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr:first-child td')).map(txt);
 p=await load('season=1&board=catluck');R.clH1=txt(p.d.querySelector('h1'));R.clHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);
 p=await load('season=1&board=weekly','old/');R.oldNote=txt(p.d.querySelector('.snapbar .rnote'));R.oldSelects=p.d.querySelectorAll('.snapbar select').length;R.oldChips=p.d.querySelectorAll('#snapbar .seg button').length;
 p=await load('season=1&board=luck&range=4-4');R.oneWeek=[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).map(function(r){return [r.cells[1].className.replace('cat ',''),r.cells[2].className.replace('total sep ','')]});
 R.alias={};
 for(var b of ['roto','totals','weekly','power','matrix','allplay','real','luck','luckweeks','catluck','matchlog','kings','boom','standings','records','sos','odds','outlook','form','split','performance']){
  p=await load('season=1&board='+b);R.alias[b]=[txt(p.d.querySelector('h1')),txt(p.d.querySelector('#nav .active')),txt(p.d.querySelector('#lensbar button.on')),p.w.location.search];}
 p=await load('season=1&board=real');R.tabs=[].slice.call(p.d.querySelectorAll('#nav button')).map(txt);R.lenses=[].slice.call(p.d.querySelectorAll('#lensbar .seg:first-child button')).map(txt);R.realHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);
 p=await load('season=1&board=standings&lens=odds');R.odH1=txt(p.d.querySelector('h1'));R.odHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st:not(.acct) thead tr:last-child th')).map(txt);R.odRows=p.d.querySelectorAll('.tscroll .st:not(.acct) tbody tr').length;R.odBars=p.d.querySelectorAll('.tscroll .st tbody tr:first-child .hb i').length;R.odIn=p.d.querySelectorAll('.tscroll .st tbody tr:first-child .hb i.po').length;R.odRange=p.d.querySelectorAll('#snapbar button').length;R.odPct=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td.total'));

 p=await load('season=1&board=luck&lens=summary&range=1-3');R.smHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.smRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.smBasisButtons=[].slice.call(p.d.querySelectorAll('#lensbar .seg:nth-child(2) button')).map(txt);R.smRec=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:nth-child(2)'));
 p=await load('season=1&board=luck&lens=summary&basis=cats&range=1-3');R.smcHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.smcH1=txt(p.d.querySelector('h1'));R.smcRec=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:nth-child(2)'));
 p=await load('season=1&board=luck&lens=cat&range=1-3');R.catHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.catBasisButtons=p.d.querySelectorAll('#lensbar .seg:nth-child(2) button').length;
 p=await load('season=1&board=outlook&lens=sos&range=1-3');R.sosH1=txt(p.d.querySelector('h1'));R.sosHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.sosRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.sosRec=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:nth-child(2)'));
 p=await load('season=1&board=outlook&lens=sos&basis=cats&range=1-3');R.sosCatRec=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:nth-child(2)'));
 p=await load('season=1&board=outlook&lens=sos&per=rest');R.sosRestH1=txt(p.d.querySelector('h1'));R.sosRestRec=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:nth-child(2)'));R.sosRestRange=p.d.querySelectorAll('#snapbar button').length;R.sosPeriods=[].slice.call(p.d.querySelectorAll('#lensbar .seg button')).map(txt);R.sosRestUrl=p.w.location.search;
 p=await load('season=1&board=outlook&lens=sos&per=rest&basis=cats');R.sosRestCat=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:nth-child(2)'));
 p=await load('season=1&board=outlook&lens=odds','pre/');R.preBanner=txt(p.d.querySelector('.pre'));R.preSub=txt(p.d.querySelector('.view-subtitle'));
 p=await load('season=1&board=outlook&lens=odds','none/');R.noneMsg=txt(p.d.querySelector('.msg'));R.noneTabs=[].slice.call(p.d.querySelectorAll('#nav button')).map(txt);
 p=await load('season=1&board=performance&lens=form','long/');R.fmChips=[].slice.call(p.d.querySelectorAll('#lensbar .seg:nth-child(2) button')).map(txt);R.fmRange=p.d.querySelectorAll('#snapbar button').length;p.d.querySelectorAll('#lensbar .seg:nth-child(2) button')[1].click();R.fmH1=txt(p.d.querySelector('h1'));R.fmUrl=p.w.location.search;R.fmChange=(function(){var hs=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt),i=hs.indexOf('Change (pts)'),sh={};[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).forEach(function(r){r.cells[i].className.split(' ').forEach(function(k){if(/^(green|red)-/.test(k))sh[k]=1;});});return Object.keys(sh);})();R.fmHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.fmRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;
 p=await load('season=1&board=performance&lens=form');R.fmShort=txt(p.d.querySelector('h1'));R.fmShortChips=[].slice.call(p.d.querySelectorAll('#lensbar .seg:nth-child(2) button')).map(txt);
 p=await load('season=1&board=performance&lens=split&range=2-3');R.spHeads=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);R.spRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.spH1=txt(p.d.querySelector('h1'));
 R.colour=[];
 for(var spec of COLOURS){p=await load('season=1&'+spec[0]);var hs=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);
  spec[1].forEach(function(hd){var i=hs.indexOf(hd),sh={};if(i>=0)[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).forEach(function(r){var c=r.cells[i];if(c)c.className.split(' ').forEach(function(k){if(/^(green|red)-(strong|soft)$/.test(k))sh[k]=1;});});R.colour.push([spec[0],hd,i,Object.keys(sh)]);});}
 p=await load('season=1&board=performance&lens=split','long/');(function(){var hs=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);['Strong Win%','Weak Win%'].forEach(function(hd){var i=hs.indexOf(hd),sh={};[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).forEach(function(r){var c=r.cells[i];if(c)c.className.split(' ').forEach(function(k){if(/^(green|red)-(strong|soft)$/.test(k))sh[k]=1;});});R.colour.push(['board=performance&lens=split (long season)',hd,i,Object.keys(sh)]);});})();
 p=await load('season=1&board=outlook&lens=odds');R.accSummary=txt(p.d.querySelector('.acc summary'));R.accRows=[].slice.call(p.d.querySelectorAll('.acct tbody tr')).map(function(r){return [].slice.call(r.cells).map(txt)});R.movers=txt(p.d.querySelector('.movers'));R.moverChips=p.d.querySelectorAll('.movers .mv').length;R.odSub=txt(p.d.querySelector('.view-subtitle'));R.odNote=txt(p.d.querySelector('details.how p'));
 for(var q of ['board=roto','board=luck&lens=summary','board=outlook&lens=odds','board=outlook&lens=sos&per=rest','board=performance&lens=form','board=performance&lens=trends']){p=await load('season=1&'+q,'settled/');R.settledStatus=txt(p.d.querySelector('#status'));R.settledRows=(R.settledRows||[]).concat([p.d.querySelectorAll('.tscroll .st tbody tr').length]);}
 p=await load('week=4&view=roto','settled/');R.settledWeekStatus=txt(p.d.querySelector('#status'));R.settledWeekH1=txt(p.d.querySelector('h1'));
 p=await load('season=1&board=outlook&lens=odds','early/');R.earlyMovers=p.d.querySelectorAll('.movers').length;R.earlyAcc=p.d.querySelectorAll('.acc,.accline').length;R.earlyRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;
 R.spark={};
 for(var q of ['board=luck&lens=summary','board=weekly','board=outlook&lens=odds']){p=await load('season=1&'+q);R.spark[q]=[p.d.querySelectorAll('.tscroll td.trend svg').length,p.d.querySelectorAll('.tscroll td.trend svg polyline').length,p.d.querySelectorAll('.tscroll td.trend svg title').length,p.d.querySelectorAll('.tscroll td.trend svg line.z').length];}
 p=await load('season=1&board=performance&lens=trends&meas=luck&me=7');R.trH1=txt(p.d.querySelector('h1'));R.trLines=p.d.querySelectorAll('svg.trendchart polyline.tl').length;R.trMe=p.d.querySelectorAll('svg.trendchart polyline.tl.me').length;R.trLabels=p.d.querySelectorAll('svg.trendchart text.lb').length;R.trBase=p.d.querySelectorAll('svg.trendchart polyline.bl').length;R.trBaseText=txt(p.d.querySelector('svg.trendchart text.blt'));R.trCap=txt(p.d.querySelector('svg.trendchart text.cap'));R.trMarks=p.d.querySelectorAll('svg.trendchart circle.mk').length;R.trAria=p.d.querySelector('svg.trendchart').getAttribute('aria-label');
 var ms=p.d.querySelector('#lensbar select[aria-label="Measure"]');ms.value='rank';ms.dispatchEvent(new p.w.Event('change'));R.trH1b=txt(p.d.querySelector('h1'));R.trUrl=p.w.location.search;
 p=await load('season=1&board=performance&lens=trends&meas=win&tbl=1');R.trTblRows=p.d.querySelectorAll('.tscroll .st tbody tr').length;R.trTblCols=p.d.querySelectorAll('.tscroll .st thead tr:last-child th').length;R.trTblCell=txt(p.d.querySelector('.tscroll .st tbody tr:first-child td:last-child'));
 R.plain=[];
 for(var spec of PLAIN){p=await load('season=1&'+spec[0]);var hs2=[].slice.call(p.d.querySelectorAll('.tscroll .st thead tr:last-child th')).map(txt);
  spec[1].forEach(function(hd){var i=hs2.indexOf(hd),sh={};if(i>=0)[].slice.call(p.d.querySelectorAll('.tscroll .st tbody tr')).forEach(function(r){var c=r.cells[i];if(c)c.className.split(' ').forEach(function(k){if(/^(green|red)-(strong|soft)$/.test(k))sh[k]=1;});});R.plain.push([spec[0],hd,i,Object.keys(sh)]);});}
 R.copy=[];
 for(var q of COPYQ){p=await load(q);R.copy.push([q,txt(p.d.querySelector('details.how p')),txt(p.d.querySelector('.view-subtitle')),[].slice.call(p.d.querySelectorAll('.tscroll th[title]')).map(function(e){return e.getAttribute('title')})]);}
 R.strip=[].slice.call(p.d.querySelectorAll('.strip button')).map(txt).slice(0,3);
 R.fit=[];
 for(var q of FITS){p=await load('static=1&season=1&'+q,'long/',1680);var sc=p.d.querySelector('.tscroll');R.fit.push([q,sc?sc.scrollWidth-sc.clientWidth:null,txt(p.d.querySelector('h1')),sc&&sc.querySelector('table').style.fontSize||'']);}
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
        main = golden.build_report(18, 4, regular=10, divisions=True)
        main["odds"].update(complete=True, scheduleWeeks=len(main["odds"]["remaining"]))               # the full schedule is read (what a finished pass gives)
        yr.write_html(main, cls.site)
        pre = json.loads(json.dumps(main))
        pre["odds"].update(complete=False, scheduleWeeks=3, sims=50000, margin=0.44)
        yr.write_html(pre, os.path.join(cls.site, "pre"))
        none = json.loads(json.dumps(main))
        none["odds"] = None
        yr.write_html(none, os.path.join(cls.site, "none"))
        pages = golden.build_pages(18, 4, 7, regular=10, divisions=True)                                 # Yahoo has turned to week 5: week 4 is over, its corrections still pending
        settled = test_current_week.report(pages, test_current_week.Fake(pages, 5, test_current_week.corrections_page(26, 22)), tempfile.mkdtemp())
        yr.write_html(settled, os.path.join(cls.site, "settled"))
        yr.write_html(golden.build_report(18, 2, regular=10, divisions=True), os.path.join(cls.site, "early"))                  # one finished week: no history, nothing to forecast yet
        yr.write_html(golden.build_report(18, 18, regular=20, divisions=True), os.path.join(cls.site, "long"))      # a full-length season: wide week grids
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
        self.assertIn("Category Luck by Week", self.R["cwH1"])                           # the old ?lens=catweek link: By week with the Categories switch on
        self.assertIn("basis=cats", self.R["cwUrl"])
        self.assertEqual(self.R["cwBasis"], "Categories")
        self.assertEqual(self.R["cwCols"], 1 + 2 + 2)                                    # team, two weeks, the total and the rank: nothing else mixed in
        self.assertNotEqual(self.R["cwCells"][:2], self.R["cwPickCells"][:2])            # picking PTS changes the numbers
        self.assertIn("· PTS", self.R["cwPickH1"])
        self.assertIn("Category Luck", self.R["clH1"])                                   # board=catluck still opens the by-category view
        self.assertEqual(self.R["catHeads"], ["Team", "Won", "Expected", "Luck", "FG%", "FT%", "3PTM", "PTS", "REB", "AST", "ST", "BLK", "TO", "Rank"])   # no matchup luck mixed in
        self.assertEqual(self.R["catBasisButtons"], 0)                                   # by category is always categories: no switch

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
                "catluck": ("Category Luck", "Luck", "By category"), "matchlog": ("Matchup Log", "Luck", "Matchup Log"), "kings": ("Category Kings", "Performance", "Category Kings"),
                "boom": ("Recent Form", "Performance", "Recent form"), "standings": ("Roto Rank", "Standings", "Season Roto"), "records": ("Recent Form", "Performance", "Recent form"),
                "form": ("Recent Form", "Performance", "Recent form"), "split": ("Vs Strong", "Performance", "Vs strong / weak"), "performance": ("Recent Form", "Performance", "Recent form"),
                "sos": ("Strength of Schedule", "Outlook", "Strength of schedule"), "odds": ("Playoff Odds", "Outlook", "Playoff odds"), "outlook": ("Playoff Odds", "Outlook", "Playoff odds")}
        for board, (title, tab, lens) in want.items():
            h1, active_tab, active_lens, search = self.R["alias"][board]
            self.assertIn(title, h1, board)
            self.assertEqual((active_tab, active_lens), (tab, lens), board)
            self.assertIn("lens=", search, board)                                   # the address is rewritten to the new form (board=<tab>&lens=<view>)

    def test_five_tabs_with_the_views_of_the_open_tab_under_them(self):
        self.assertEqual(self.R["tabs"], ["Standings", "All-Play", "Luck", "Outlook", "Performance"])
        self.assertEqual(self.R["lenses"], ["Summary", "By week", "By category", "Matchup Log"])

    def test_the_summary_follows_the_matchups_or_categories_switch(self):
        self.assertEqual(self.R["smBasisButtons"], ["Matchups", "Categories"])
        self.assertEqual(self.R["smHeads"], ["Team", "Record", "Wins", "Expected wins", "Luck", "Luck trend", "Rank", "Expected rank", "Places vs expected"])
        self.assertEqual(self.R["smcHeads"], ["Team", "Category record", "Categories won", "Expected categories", "Category luck", "Luck trend", "Rank", "Expected rank", "Places vs expected"])
        self.assertIn("Category Record & Luck", self.R["smcH1"])
        self.assertEqual(self.R["smRows"], 18)
        self.assertEqual(len(self.R["smRec"].split("-")), 3)                              # a matchup record: W-L-T over a few matchups
        self.assertGreater(sum(int(x) for x in self.R["smcRec"].split("-")), 20)          # a category record: 9 categories a week

    def test_playoff_odds_view(self):
        self.assertIn("Playoff Odds", self.R["odH1"])
        self.assertEqual(self.R["odHeads"], ["Team", "Div", "Playoffs", "Top seed", "Projected rank", "Odds trend", "Finishing place"])
        self.assertEqual((self.R["odRows"], self.R["odBars"], self.R["odIn"]), (18, 18, 6))        # a bar per place, the six playoff places in green
        self.assertEqual(self.R["odRange"], 0)                                                       # the week range does not apply to it
        self.assertRegex(self.R["odPct"], r"^(>99|<1|\d+)%$")

    def test_strength_of_schedule_is_the_opponents_record_on_either_basis(self):
        self.assertIn("Strength of Schedule", self.R["sosH1"])
        self.assertEqual(self.R["sosHeads"], ["Team", "Opponents' record", "SOS", "Rank"])
        self.assertEqual(self.R["sosRows"], 18)
        self.assertEqual(sum(int(x) for x in self.R["sosRec"].split("-")), 3 * 3)                  # 3 weeks: 3 opponents x 3 games each (every game of theirs counts)
        self.assertEqual(sum(int(x) for x in self.R["sosCatRec"].split("-")), 9 * 3 * 3)           # nine categories to a matchup
        self.assertIn("Rest of season", self.R["sosPeriods"])
        self.assertIn("Rest of Season", self.R["sosRestH1"])
        self.assertEqual(sum(int(x) for x in self.R["sosRestRec"].split("-")), 7 * 4)              # seven weeks left x the 4 games of each opponent, the week in progress included
        self.assertEqual(sum(int(x) for x in self.R["sosRestCat"].split("-")), 7 * 4 * 9)
        self.assertEqual(self.R["sosRestRange"], 0)                                                # the week range does not apply to what is still to come
        self.assertIn("per=rest", self.R["sosRestUrl"])

    def test_the_odds_say_when_the_schedule_is_incomplete_or_missing(self):
        self.assertIn("Preliminary: 3 of 7", self.R["preBanner"])
        self.assertIn("played from today, 50,000 times", self.R["preSub"])
        self.assertIn("No playoff odds in this report yet", self.R["noneMsg"])
        self.assertEqual(self.R["noneTabs"][3], "Outlook")                                # the tab is still there, with the explanation

    def test_every_season_view_fits_in_the_image_on_a_full_length_season(self):
        self.assertEqual(len(self.R["fit"]), 18)
        for q, overflow, h1, _ in self.R["fit"]:
            self.assertIsNotNone(h1, q)
            self.assertLessEqual(overflow or 0, 1, "%s runs %s px wider than the image" % (q, overflow))        # a chart has no table and scales to the picture

    def test_every_comparing_column_uses_the_rank_shades(self):
        for q, header, index, shades in self.R["colour"]:
            self.assertGreaterEqual(index, 0, "%s: no column %r" % (q, header))
            self.assertTrue(any(s.startswith("green") for s in shades) and any(s.startswith("red") for s in shades), "%s: %r has no green and red (%s)" % (q, header, shades))

    def test_supporting_columns_stay_plain_so_each_table_says_only_one_or_two_things(self):
        for q, header, index, shades in self.R["plain"]:
            self.assertGreaterEqual(index, 0, "%s: no column %r" % (q, header))
            self.assertEqual(shades, [], "%s: %r should not be coloured" % (q, header))

    def test_weeks_are_labelled_wk_not_w(self):
        self.assertEqual(self.R["strip"], ["Wk 1", "Wk 2", "Wk 3"])

    def test_the_explanations_stay_short_and_plain(self):
        banned = ("log5", "shrunk", "competition rank", "basis", "Exp.", "Diff", "Cat luck", "Cat W-L-T", "Opp record")
        for q, note, sub, tips in self.R["copy"]:
            self.assertTrue(note, q)
            self.assertLessEqual(len(note.split()), 60, "%s: the note has %d words" % (q, len(note.split())))
            self.assertLessEqual(len((sub or "").split()), 16, "%s: the subtitle is too long" % q)
            for tip in tips:
                self.assertLessEqual(len(tip.split()), 16, "%s: tooltip %r is too long" % (q, tip))
            for text in [note, sub or ""] + tips:
                for word in banned:
                    self.assertNotIn(word, text, "%s: %r in %r" % (q, word, text[:60]))

    def test_recent_form_has_selectable_windows_and_no_week_range(self):
        self.assertEqual(self.R["fmChips"], ["Last 3", "Last 5", "Last 8"])                  # an 18-week season offers all three windows
        self.assertEqual(self.R["fmRange"], 0)                                               # the week range does not apply
        self.assertIn("Last 5", self.R["fmH1"])
        self.assertIn("win=5", self.R["fmUrl"])
        self.assertEqual(self.R["fmHeads"], ["Team", "Last 5", "Win%", "Season Win%", "Change (pts)", "Stats said", "By week"])
        self.assertEqual(self.R["fmRows"], 18)
        self.assertEqual(self.R["fmShortChips"], ["Last 3"])                                 # three finished weeks: only the 3-week window fits

    def test_recent_form_change_is_coloured_when_form_moved(self):
        self.assertTrue(any(s.startswith("green") for s in self.R["fmChange"]) and any(s.startswith("red") for s in self.R["fmChange"]), self.R["fmChange"])

    def test_vs_strong_and_weak_teams(self):
        self.assertEqual(self.R["spHeads"], ["Team", "Vs strong", "Strong Win%", "Vs weak", "Weak Win%"])
        self.assertEqual(self.R["spRows"], 18)
        self.assertIn("Weeks 2-3", self.R["spH1"])                                           # follows the week range

    def test_small_trend_lines_sit_in_four_tables_one_per_team(self):
        for q, (svgs, lines, titles, baselines) in self.R["spark"].items():
            self.assertEqual((svgs, lines, titles, baselines), (18, 18, 18, 18), q)               # every line has a dashed baseline to compare against

    def test_the_trends_chart_has_a_line_per_team_and_highlights_yours(self):
        self.assertIn("Cumulative luck", self.R["trH1"])
        self.assertEqual((self.R["trLines"], self.R["trMe"]), (18, 1))
        self.assertGreaterEqual(self.R["trLabels"], 6)                                      # top and bottom three, and your team when it is not among them
        self.assertEqual(self.R["trBase"], 1)                                                  # the dashed baseline of an average team, with its label and a caption
        self.assertIn("as deserved", self.R["trBaseText"])
        self.assertIn("luckier", self.R["trCap"])
        self.assertEqual(self.R["trMarks"], 3)                                                 # your real matchup results, one mark per week
        self.assertIn("Line chart", self.R["trAria"])
        self.assertIn("Season roto rank", self.R["trH1b"])
        self.assertIn("meas=rank", self.R["trUrl"])
        self.assertEqual(self.R["trTblRows"], 18)                                           # the same numbers as a table
        self.assertEqual(self.R["trTblCols"], 1 + 3)                                         # team and three finished weeks
        self.assertRegex(self.R["trTblCell"], r"^\d+\.\d%$")

    def test_the_odds_show_how_reliable_they_have_been_and_who_moved(self):
        self.assertIn("the favourite won", self.R["accSummary"])
        self.assertIn("coin flip", self.R["accSummary"])
        self.assertGreaterEqual(len(self.R["accRows"]), 1)
        self.assertEqual(sum(int(r[1]) for r in self.R["accRows"]), int(re.search(r"of (\d+) matchups", self.R["accSummary"]).group(1)))     # the bins add up to the games
        self.assertRegex(self.R["movers"], r"^Since Wk \d+: ")
        self.assertRegex(self.R["movers"], r"[+\u2212]\d+")
        self.assertLessEqual(self.R["moverChips"], 6)
        self.assertIn("played from today", self.R["odSub"])
        self.assertIn("snapshot, not a forecast", self.R["odNote"])
        self.assertIn("not modelled", self.R["odNote"])

    def test_a_week_yahoo_has_closed_is_final_with_a_note_about_pending_corrections(self):
        self.assertIn("Wk 4 is complete; Yahoo may still correct box scores until Mon 16 Nov (4 pending, 22 arrived too late to count)", self.R["settledStatus"])
        self.assertNotIn("still being played", self.R["settledStatus"])
        self.assertNotIn("in progress", self.R["settledStatus"])
        self.assertEqual([n >= 18 for n in self.R["settledRows"][:5]], [True] * 5, self.R["settledRows"])      # every table still draws without a live week (odds adds division rows; trends is a chart)
        self.assertIn("Wk 4 is complete", self.R["settledWeekStatus"])
        self.assertIn("Week 4", self.R["settledWeekH1"])

    def test_with_one_finished_week_there_is_nothing_to_grade_and_nobody_moved(self):
        self.assertEqual((self.R["earlyMovers"], self.R["earlyAcc"]), (0, 0))
        self.assertEqual(self.R["earlyRows"], 18)                                              # the table itself is still there

    def test_matchup_log_has_a_row_per_team_and_week(self):
        self.assertEqual(self.R["mlRows"], 3 * 18)
        self.assertIn("Weeks 1-3", self.R["mlH1"])

    def test_luck_by_week_has_a_column_per_week_in_the_range(self):
        self.assertIn("Weeks 2-3", self.R["lwH1"])
        self.assertEqual((self.R["lwCols"], self.R["lwRows"]), (1 + 2 + 2, 18))      # team, two weeks, Luck, Rank
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
        self.assertEqual((self.R["week0"], self.R["week1"], self.R["week2"]), ("Wk 3", "Wk 2", "Wk 2"))

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
