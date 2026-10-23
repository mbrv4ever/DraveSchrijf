# Maakt assets/icon.png + assets/icon.ico voor DraveSchrijf (eigen ontwerp: open boek met een gouden pen). Pillow nodig.
import os
from PIL import Image, ImageDraw, ImageFilter

HIER = os.path.dirname(os.path.abspath(__file__))
N = 512
img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((16, 16, N - 16, N - 16), radius=96, fill=(18, 20, 30, 255), outline=(111, 163, 214, 255), width=10)
# zachte gloed
gl = Image.new("RGBA", (N, N), (0, 0, 0, 0))
ImageDraw.Draw(gl).ellipse((90, 150, N - 90, N - 60), fill=(111, 163, 214, 90))
img = Image.alpha_composite(img, gl.filter(ImageFilter.GaussianBlur(45)))
d = ImageDraw.Draw(img)
# open boek: twee bladzijden
d.polygon([(70, 190), (250, 225), (250, 420), (70, 385)], fill=(236, 236, 242, 255))
d.polygon([(442, 190), (262, 225), (262, 420), (442, 385)], fill=(214, 216, 226, 255))
d.line([(256, 222), (256, 424)], fill=(90, 96, 120, 255), width=8)
for i in range(5):  # tekstregels
    y = 250 + i * 30
    d.line([(95, y - 4 + i * 0), (225, y + 22)], fill=(120, 126, 150, 255), width=7)
    if i < 4:
        d.line([(287, y + 22), (417, y - 4)], fill=(140, 146, 170, 255), width=7)
# gouden pen schuin erover
pen = [(370, 60), (410, 100), (250, 300), (215, 312), (226, 276)]
d.polygon(pen, fill=(255, 179, 71, 255), outline=(150, 95, 20, 255))
d.line([(392, 80), (238, 290)], fill=(200, 125, 30, 255), width=5)
d.polygon([(215, 312), (226, 276), (240, 292)], fill=(40, 40, 50, 255))
os.makedirs(os.path.join(HIER, "assets"), exist_ok=True)
img.save(os.path.join(HIER, "assets", "icon.png"))
img.save(os.path.join(HIER, "assets", "icon.ico"), format="ICO",
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icoon klaar")
