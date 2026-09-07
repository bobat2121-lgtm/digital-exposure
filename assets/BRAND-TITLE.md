# Imprint title

The public title uses Georgia Bold for **Digital Credit**, Lato Regular for the
bookends, and a small orange endpoint. The responsive website keeps the approved
33px desktop scale and reduces the endpoint from 6px to 5px on phones.

`title-imprint.png` is a transparent fixed wordmark rendered at 160px type and
reduced with Lanczos for PNG exports. It preserves the chosen Georgia design on
the Linux Streamlit host without redistributing or requiring the Georgia font.
The bundled Lato font retains its existing license. No Microsoft font file is
bundled or served.

To recreate the artwork on a machine with a licensed Georgia Bold installation:

```powershell
python scripts/build_brand_title.py --serif-font C:/Windows/Fonts/georgiab.ttf
```
