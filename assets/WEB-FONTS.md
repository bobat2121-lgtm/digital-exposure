The public page uses WOFF2 subsets of the bundled Lato fonts, internally named
**Credit Report Sans** to respect Lato's reserved font name. They retain Latin,
Greek, punctuation, currency and mathematical characters used in the report.
Copyright and license records remain embedded; the SIL Open Font License is
included in `FONT-LICENSE.txt`. The original TTF files remain unchanged for PNG
exports and archived layouts.

Rebuild with `python scripts/build_webfonts.py` after installing the optional
build tools `fonttools` and `brotli`. The web application has no additional
runtime dependency and makes no external font requests.
