# -*- coding: utf-8 -*-
# Inject the "free location report" lead-form section into the bundled
# landing page template (danielstay.html), same approach as make_inject.py /
# make_responsive.py: insert <style>/<script> right before the escaped
# </body> marker of the JSON-encoded bundle template. Idempotent (sentinel).
#
# Notes
# - The template is a JSON string, so the payload is JSON-encoded here and
#   every "</" is written as "</" (so the outer <script> is not closed).
# - The old consult form hook (make_inject.py) grabs
#   document.getElementsByTagName('select')[0] and inputs whose placeholder
#   contains '홍길동' / '010'. This section therefore uses NO <select>
#   (status is a chip radio group) and avoids those placeholders, so the
#   old hook keeps reading the original #apply form.
# - Dry run for testing (no network): set window.__DS_LEAD_DRYRUN = true in the
#   console; submit then only console.logs the POST url + body.
import io, json, sys

FILE = "danielstay.html"
SENTINEL = "/*DS-LEADFORM*/"

FORM_URL = ("https://docs.google.com/forms/d/e/"
            "1FAIpQLSeFHUNwnXuxUbc5QNEI2Y8cSp84OODALZkscggCQcvmdHZn8Q/formResponse")
CONSENT = ("리포트 발송과 상담 안내를 위해 이름·연락처·이메일·주소를 수집하며, "
           "목적 달성 후 1년 내 파기합니다. 동의합니다.")
KAKAO = "http://pf.kakao.com/_APzxbX"

CSS = SENTINEL + """
#ds-lead{padding:24px 0 96px;font-family:'Pretendard Variable',Pretendard,-apple-system,BlinkMacSystemFont,sans-serif;color:#1A1712}
#ds-lead *{box-sizing:border-box}
#ds-lead .dl-wrap{max-width:1180px;margin:0 auto;padding:0 40px}
#ds-lead .dl-box{display:grid;grid-template-columns:0.9fr 1.1fr;gap:56px;align-items:start;background:#0E4633;border-radius:24px;padding:56px;color:#fff}
#ds-lead .dl-eyebrow{font-size:13px;font-weight:700;letter-spacing:.04em;color:#F3B59F;margin-bottom:14px}
#ds-lead h2{font-size:34px;line-height:1.3;font-weight:700;margin:0 0 16px;color:#fff;word-break:keep-all}
#ds-lead .dl-desc{font-size:16px;line-height:1.7;color:rgba(255,255,255,.82);margin:0 0 24px;word-break:keep-all}
#ds-lead .dl-points{list-style:none;padding:0;margin:0 0 28px;display:grid;gap:10px}
#ds-lead .dl-points li{font-size:14.5px;color:rgba(255,255,255,.9);padding-left:22px;position:relative;word-break:keep-all}
#ds-lead .dl-points li:before{content:'';position:absolute;left:2px;top:7px;width:8px;height:8px;border-radius:50%;background:#E8674C}
#ds-lead .dl-kakao{display:inline-block;font-size:13px;color:rgba(255,255,255,.75);text-decoration:underline;text-underline-offset:3px}
#ds-lead .dl-kakao:hover{color:#fff}
#ds-lead .dl-card{background:#fff;border-radius:16px;padding:28px;color:#1A1712;box-shadow:0 10px 40px rgba(0,0,0,.18)}
#ds-lead .dl-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
#ds-lead .dl-full{grid-column:1/-1}
#ds-lead label.dl-l{display:block;font-size:13.5px;font-weight:600;margin-bottom:7px;color:#1A1712}
#ds-lead label.dl-l span{color:#E8674C}
#ds-lead input.dl-in{width:100%;font:inherit;font-size:15px;color:#1A1712;background:#fff;border:1px solid #D2C9BB;border-radius:12px;padding:12px 14px;outline:none;transition:border-color .15s,box-shadow .15s}
#ds-lead input.dl-in:focus{border-color:#16704F;box-shadow:0 0 0 3px rgba(22,112,79,.15)}
#ds-lead input.dl-in.dl-err{border-color:#E8674C}
#ds-lead .dl-chips{display:flex;flex-wrap:wrap;gap:8px}
#ds-lead .dl-chip{font:inherit;font-size:14px;padding:9px 14px;border-radius:999px;border:1px solid #D2C9BB;background:#fff;color:#423C32;cursor:pointer;transition:all .15s}
#ds-lead .dl-chip[aria-checked=true]{background:#0E4633;border-color:#0E4633;color:#fff;font-weight:600}
#ds-lead .dl-chips.dl-err .dl-chip{border-color:#E8674C}
#ds-lead .dl-consent{display:flex;gap:10px;align-items:flex-start;font-size:13px;line-height:1.55;color:#423C32;background:#FAF8F5;border:1px solid #E6E0D7;border-radius:12px;padding:12px 14px;cursor:pointer;word-break:keep-all}
#ds-lead .dl-consent.dl-err{border-color:#E8674C}
#ds-lead .dl-consent input{margin:2px 0 0;width:18px;height:18px;flex:0 0 18px;accent-color:#0E4633}
#ds-lead .dl-btn{width:100%;font:inherit;font-size:17px;font-weight:600;color:#fff;background:#E8674C;border:0;border-radius:14px;padding:16px 28px;cursor:pointer;transition:filter .15s,opacity .15s}
#ds-lead .dl-btn:hover{filter:brightness(.95)}
#ds-lead .dl-btn[disabled]{opacity:.6;cursor:default}
#ds-lead .dl-note{font-size:12px;color:#7E7567;margin-top:10px;text-align:center}
@media(max-width:1024px){#ds-lead .dl-wrap{padding:0 32px}#ds-lead .dl-box{gap:36px;padding:44px}#ds-lead h2{font-size:30px}}
@media(max-width:768px){#ds-lead .dl-wrap{padding:0 24px}#ds-lead .dl-box{grid-template-columns:1fr;gap:28px;padding:36px 28px}#ds-lead h2{font-size:27px}#ds-lead .dl-points{margin-bottom:18px}}
@media(max-width:480px){#ds-lead{padding:8px 0 64px}#ds-lead .dl-wrap{padding:0 16px}#ds-lead .dl-box{padding:28px 18px;border-radius:18px}#ds-lead h2{font-size:23px}#ds-lead .dl-desc{font-size:15px}#ds-lead .dl-card{padding:20px 16px}#ds-lead .dl-grid{grid-template-columns:1fr;gap:14px}}
"""

JS = r"""
(function(){
if(window.__dsLeadInit)return;window.__dsLeadInit=1;
var URL_=%(url)s,CONSENT=%(consent)s,KAKAO=%(kakao)s;
var STAT=['공실','월세 중','직접 거주 중','매수 검토 중'];
function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
function toast(m){var d=document.createElement('div');d.textContent=m;
d.style.cssText='position:fixed;left:50%%;bottom:32px;transform:translateX(-50%%);max-width:calc(100vw - 32px);text-align:center;background:#0E4633;color:#fff;padding:14px 22px;border-radius:10px;font:600 15px -apple-system,BlinkMacSystemFont,sans-serif;z-index:99999;box-shadow:0 6px 24px rgba(0,0,0,.25)';
document.body.appendChild(d);setTimeout(function(){d.style.transition='opacity .5s';d.style.opacity='0';},2600);setTimeout(function(){d.remove();},3200);}
function build(){
var s=document.createElement('section');s.id='ds-lead';
var chips=STAT.map(function(t){return '<button type=\'button\' class=\'dl-chip\' role=\'radio\' aria-checked=\'false\' data-v=\''+esc(t)+'\'>'+esc(t)+'</button>';}).join('');
s.innerHTML=
'<div class=\'dl-wrap\'><div class=\'dl-box\'>'+
 '<div class=\'dl-copy\'>'+
  '<div class=\'dl-eyebrow\'>무료 입지 리포트</div>'+
  '<h2>우리 오피스텔, 단기임대로 팔릴까?<br>무료 입지 리포트</h2>'+
  '<p class=\'dl-desc\'>주소만 남겨주시면 반경 500m 실제 가동률과 주간 시세를 조사해 무료로 보내드립니다.</p>'+
  '<ul class=\'dl-points\'><li>반경 500m 단기임대 실제 가동률</li><li>주변 숙소 주간 시세 분포</li><li>리포트는 이메일로 발송</li></ul>'+
  '<a class=\'dl-kakao\' href=\''+KAKAO+'\' target=\'_blank\' rel=\'noopener\'>궁금한 점은 카카오톡으로 문의하기 &rarr;</a>'+
 '</div>'+
 '<div class=\'dl-card\'><div class=\'dl-grid\'>'+
  '<div><label class=\'dl-l\' for=\'dl-name\'>이름<span>*</span></label><input class=\'dl-in\' id=\'dl-name\' autocomplete=\'name\' placeholder=\'이름\'></div>'+
  '<div><label class=\'dl-l\' for=\'dl-phone\'>연락처<span>*</span></label><input class=\'dl-in\' id=\'dl-phone\' type=\'tel\' inputmode=\'tel\' autocomplete=\'tel\' placeholder=\'휴대폰 번호\'></div>'+
  '<div class=\'dl-full\'><label class=\'dl-l\' for=\'dl-email\'>이메일<span>*</span></label><input class=\'dl-in\' id=\'dl-email\' type=\'email\' autocomplete=\'email\' placeholder=\'리포트 받을 이메일\'></div>'+
  '<div class=\'dl-full\'><label class=\'dl-l\' for=\'dl-addr\'>오피스텔 주소 또는 가까운 역 이름<span>*</span></label><input class=\'dl-in\' id=\'dl-addr\' placeholder=\'예) 영통역 / 수원시 영통구 ○○로 00\'></div>'+
  '<div class=\'dl-full\'><span class=\'dl-l\' style=\'display:block;font-size:13.5px;font-weight:600;margin-bottom:7px\'>현재 상태<span style=\'color:#E8674C\'>*</span></span><div class=\'dl-chips\' role=\'radiogroup\' aria-label=\'현재 상태\'>'+chips+'</div></div>'+
  '<label class=\'dl-consent dl-full\'><input type=\'checkbox\' id=\'dl-agree\'><span>'+esc(CONSENT)+'</span></label>'+
  '<div class=\'dl-full\'><button type=\'button\' class=\'dl-btn\' id=\'dl-submit\'>무료 리포트 받기</button><div class=\'dl-note\'>입력하신 정보는 리포트 발송과 상담 안내에만 사용됩니다.</div></div>'+
 '</div></div>'+
'</div></div>';
var status='';
s.querySelectorAll('.dl-chip').forEach(function(b){b.addEventListener('click',function(){
 status=b.getAttribute('data-v');s.querySelectorAll('.dl-chip').forEach(function(x){x.setAttribute('aria-checked',x===b?'true':'false');});
 s.querySelector('.dl-chips').classList.remove('dl-err');});});
s.addEventListener('input',function(e){if(e.target.classList)e.target.classList.remove('dl-err');});
s.querySelector('#dl-agree').addEventListener('change',function(){s.querySelector('.dl-consent').classList.remove('dl-err');});
function $(id){return s.querySelector('#'+id);}
s.querySelector('#dl-submit').addEventListener('click',function(ev){
 ev.preventDefault();ev.stopPropagation();
 var f={name:$('dl-name').value.trim(),phone:$('dl-phone').value.trim(),email:$('dl-email').value.trim(),addr:$('dl-addr').value.trim()};
 var bad=null;
 function mark(id,msg){$(id).classList.add('dl-err');if(!bad)bad=msg;}
 if(!f.name)mark('dl-name','이름을 입력해 주세요');
 if(!f.phone)mark('dl-phone','연락처를 입력해 주세요');
 else if(f.phone.replace(/[^0-9]/g,'').length<9)mark('dl-phone','연락처를 확인해 주세요');
 if(!f.email)mark('dl-email','이메일을 입력해 주세요');
 else if(!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email))mark('dl-email','이메일 형식을 확인해 주세요');
 if(!f.addr)mark('dl-addr','주소 또는 역 이름을 입력해 주세요');
 if(!status){s.querySelector('.dl-chips').classList.add('dl-err');if(!bad)bad='현재 상태를 선택해 주세요';}
 if(!$('dl-agree').checked){s.querySelector('.dl-consent').classList.add('dl-err');if(!bad)bad='개인정보 수집·이용에 동의해 주세요';}
 if(bad){toast(bad);return;}
 var fields=[['entry.1912567840',f.name],['entry.238384965',f.phone],['entry.1861602072',f.email],['entry.26242271',f.addr],['entry.1885303067',status],['entry.85021570',CONSENT]];
 if(window.__DS_LEAD_DRYRUN){console.log('[ds-lead dry-run] POST '+URL_,fields,new URLSearchParams(fields).toString());window.__dsLeadLast=fields;toast('신청 완료! 리포트 준비되면 이메일로 보내드릴게요.');return;}
 var btn=this;btn.disabled=true;
 var fr=document.createElement('iframe');fr.name='dsl'+Date.now();fr.style.display='none';document.body.appendChild(fr);
 var fm=document.createElement('form');fm.action=URL_;fm.method='POST';fm.target=fr.name;fm.style.display='none';
 fields.forEach(function(p){var x=document.createElement('input');x.type='hidden';x.name=p[0];x.value=p[1];fm.appendChild(x);});
 document.body.appendChild(fm);fm.submit();
 ['dl-name','dl-phone','dl-email','dl-addr'].forEach(function(id){$(id).value='';});
 $('dl-agree').checked=false;status='';s.querySelectorAll('.dl-chip').forEach(function(x){x.setAttribute('aria-checked','false');});
 toast('신청 완료! 리포트 준비되면 이메일로 보내드릴게요.');
 setTimeout(function(){btn.disabled=false;try{fm.remove();fr.remove();}catch(e){}},5000);
});
return s;}
var sec=null;
function place(){
 if(sec&&sec.isConnected)return true;
 var anchor=document.getElementById('apply');
 if(!anchor||!anchor.parentNode)return false;
 if(!sec)sec=build();
 anchor.parentNode.insertBefore(sec,anchor);return true;}
var n=0,t=setInterval(function(){n++;place();if(n>150)clearInterval(t);},200);
if(window.MutationObserver){var mo=new MutationObserver(function(){if(sec&&!sec.isConnected)place();});
 var start=function(){mo.observe(document.body,{childList:true,subtree:true});};
 if(document.body)start();else document.addEventListener('DOMContentLoaded',start);}
})();
""" % {"url": json.dumps(FORM_URL), "consent": json.dumps(CONSENT, ensure_ascii=False),
       "kakao": json.dumps(KAKAO)}

PAYLOAD = "<style>" + CSS.strip() + "</style><script>" + JS.strip() + "</script>"

MARKER = "<\\u002Fbody>"  # template body close (escaped in the bundle)


def encode_for_template(s):
    # JSON string body (without outer quotes); "</" -> "</" like the bundle.
    enc = json.dumps(s, ensure_ascii=False)[1:-1]
    return enc.replace("</", "<\\u002F")


with io.open(FILE, "r", encoding="utf-8") as fh:
    html = fh.read()

if SENTINEL in html:
    print("ALREADY_INJECTED")
    sys.exit(0)

n = html.count(MARKER)
if n != 1:
    print("MARKER_COUNT=%d (expected 1) -- aborting" % n)
    sys.exit(1)

html = html.replace(MARKER, encode_for_template(PAYLOAD) + MARKER, 1)

with io.open(FILE, "w", encoding="utf-8") as fh:
    fh.write(html)

print("INJECTED lead form; sentinel present:", SENTINEL in html)
