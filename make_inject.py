# -*- coding: utf-8 -*-
# Inject a Google Forms submit hook into the bundled landing page template.
import io, sys

FILE = "danielstay.html"

# JS payload. Closing tag uses literal / so the outer template's <script>
# is not closed prematurely by the HTML parser (matches the bundle's own escaping).
JS = (
    "<script>(function(){"
    "var R='https://docs.google.com/forms/d/e/1FAIpQLSes3h07kTlR9xVqRtxOLlvgR5B7hyqSy5Qiv5MEVGw_8_4ROg/formResponse';"
    "var EN='entry.1023614460',EP='entry.1885249864',EI='entry.485118385';"
    "function toast(m){var d=document.createElement('div');d.textContent=m;"
    "d.style.cssText='position:fixed;left:50%;bottom:32px;transform:translateX(-50%);background:#0E4633;color:#fff;padding:14px 22px;border-radius:10px;font:600 15px -apple-system,BlinkMacSystemFont,sans-serif;z-index:99999;box-shadow:0 6px 24px rgba(0,0,0,.25)';"
    "document.body.appendChild(d);"
    "setTimeout(function(){d.style.transition='opacity .5s';d.style.opacity='0';},2600);"
    "setTimeout(function(){d.remove();},3200);}"
    "document.addEventListener('click',function(ev){"
    "var t=ev.target;var btn=t&&t.closest?t.closest('button,a,[role=button]'):null;if(!btn)return;"
    "if((btn.innerText||'').indexOf('신청하기')===-1)return;"
    "var ins=document.getElementsByTagName('input');var name,phone;"
    "for(var i=0;i<ins.length;i++){var p=ins[i].placeholder||'';"
    "if(p.indexOf('홍길동')>-1)name=ins[i];if(p.indexOf('010')>-1)phone=ins[i];}"
    "var sel=document.getElementsByTagName('select')[0];"
    "var nv=name?name.value.trim():'';var pv=phone?phone.value.trim():'';var iv=sel?sel.value:'';"
    "if(!nv||!pv){ev.preventDefault();ev.stopPropagation();toast('이름과 연락처를 입력해 주세요');return;}"
    "ev.preventDefault();ev.stopPropagation();"
    "var fr=document.createElement('iframe');fr.name='gf'+Date.now();fr.style.display='none';document.body.appendChild(fr);"
    "var f=document.createElement('form');f.action=R;f.method='POST';f.target=fr.name;f.style.display='none';"
    "function a(n,v){var x=document.createElement('input');x.type='hidden';x.name=n;x.value=v;f.appendChild(x);}"
    "a(EN,nv);a(EP,pv);a(EI,iv);document.body.appendChild(f);f.submit();"
    "if(name)name.value='';if(phone)phone.value='';"
    "toast('신청이 접수되었습니다. 곧 연락드릴게요!');"
    "setTimeout(function(){try{f.remove();fr.remove();}catch(e){}},5000);"
    "},true);})();"
    "<\\u002Fscript>"
)

MARKER = "<\\u002Fbody>"   # template body close (escaped in the bundle)

with io.open(FILE, "r", encoding="utf-8") as fh:
    html = fh.read()

if "entry.1023614460" in html:
    print("ALREADY_INJECTED")
    sys.exit(0)

n = html.count(MARKER)
if n != 1:
    print("MARKER_COUNT=%d (expected 1) -- aborting" % n)
    sys.exit(1)

html = html.replace(MARKER, JS + MARKER, 1)

with io.open(FILE, "w", encoding="utf-8") as fh:
    fh.write(html)

print("INJECTED ok; entry IDs present:", "entry.1023614460" in html)
