# -*- coding: utf-8 -*-
# Inject responsive breakpoint CSS into the bundled landing page template.
# Overrides inline (React) styles via !important media queries.
# Selectors use single quotes so the JSON-encoded template stays valid.
import io, sys

FILE = "danielstay.html"
SENTINEL = "/*RESP-BP*/"

CSS = (
    "<style>" + SENTINEL +
    "html,body{overflow-x:hidden!important;max-width:100%!important;}"
    # ---- <=1024: small laptop / tablet landscape ----
    "@media(max-width:1024px){"
      ".wrap{padding-left:32px!important;padding-right:32px!important;}"
      "[style*='font-size: 56px']{font-size:46px!important;}"
    "}"
    # ---- <=768: tablet portrait ----
    "@media(max-width:768px){"
      ".nav-links{display:none!important;}"
      "[style*='grid-template-columns: 1.08fr 0.92fr']{grid-template-columns:1fr!important;gap:8px!important;}"
      ".hero-anim{display:none!important;}"
      "[style*='grid-template-columns: repeat(3, 1fr)']{grid-template-columns:repeat(2,1fr)!important;}"
      "[style*='grid-template-columns: 1fr 1fr']{grid-template-columns:1fr!important;gap:28px!important;}"
      "[style*='font-size: 56px']{font-size:38px!important;}"
      "[style*='font-size: 46px']{font-size:34px!important;}"
      "[style*='font-size: 38px']{font-size:30px!important;}"
      "[style*='font-size: 34px']{font-size:27px!important;}"
      ".wrap{padding-left:24px!important;padding-right:24px!important;margin-left:auto!important;margin-right:auto!important;}"
    "}"
    # ---- <=480: mobile ----
    "@media(max-width:480px){"
      "[style*='grid-template-columns: repeat(4, 1fr)']{grid-template-columns:repeat(2,1fr)!important;gap:16px!important;}"
      "[style*='grid-template-columns: repeat(3, 1fr)']{grid-template-columns:1fr!important;}"
      "[style*='grid-template-columns: repeat(2, 1fr)']{grid-template-columns:1fr!important;}"
      "[style*='font-size: 56px']{font-size:31px!important;}"
      "[style*='font-size: 46px']{font-size:28px!important;}"
      "[style*='font-size: 38px']{font-size:25px!important;}"
      "[style*='font-size: 34px']{font-size:23px!important;}"
      ".wrap{padding-left:18px!important;padding-right:18px!important;margin-left:auto!important;margin-right:auto!important;}"
    "}"
    "</style>"
)

MARKER = "<\\u002Fbody>"  # template body close (escaped in the bundle)

with io.open(FILE, "r", encoding="utf-8") as fh:
    html = fh.read()

if SENTINEL in html:
    print("ALREADY_INJECTED")
    sys.exit(0)

n = html.count(MARKER)
if n != 1:
    print("MARKER_COUNT=%d (expected 1) -- aborting" % n)
    sys.exit(1)

html = html.replace(MARKER, CSS + MARKER, 1)

with io.open(FILE, "w", encoding="utf-8") as fh:
    fh.write(html)

print("INJECTED responsive CSS; sentinel present:", SENTINEL in html)
