"""Build the same compact Inter glyphs for the LCD and preview (SIL OFL)."""
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
chars = ''.join(chr(n) for n in range(32,127)) + 'áéíóúüñÁÉÍÓÚÜÑ¿¡…•→←°·'
data=[]; entries=[]; preview=[]
for size in (12,16,20):
    font=ImageFont.truetype(str(root/'assets/fonts/InterVariable.ttf'),size)
    for char in chars:
        advance=round(font.getlength(char)); left,top,right,bottom=font.getbbox(char,anchor='la')
        # Fixed line origin; preserve accents, descenders and font metrics.
        canvas=Image.new('L',(max(1,advance+3),size+8))
        ImageDraw.Draw(canvas).text((0,0),char,font=font,fill=255,anchor='la')
        box=canvas.getbbox() or (0,0,0,0)
        bitmap=canvas.crop(box); offset=len(data)
        data.extend(bitmap.tobytes())
        item={'code':ord(char),'size':size,'advance':advance,'x':box[0],'y':box[1],'w':box[2]-box[0],'h':box[3]-box[1],'offset':offset}
        entries.append(item)
out=root/'firmware/components/agentshell_ui/inter.hpp'
out.write_text('#pragma once\n#include <cstdint>\nnamespace shell {\nstruct Glyph {uint32_t code; uint8_t size,advance,x,y,w,h; uint32_t offset;};\ninline constexpr Glyph inter_glyphs[]={\n'+''.join('{'+','.join(str(g[k]) for k in ('code','size','advance','x','y','w','h','offset'))+'},\n' for g in entries)+'};\ninline constexpr uint8_t inter_pixels[]={\n'+','.join(map(str,data))+'\n};\ninline const Glyph &glyph(uint32_t code,unsigned size) {for(const auto &g:inter_glyphs)if(g.code==code&&g.size==size)return g;for(const auto &g:inter_glyphs)if(g.code==63&&g.size==size)return g;return inter_glyphs[0];}\n}\n')
(root/'assets/fonts/glyphs.json').write_text(json.dumps({'glyphs':entries,'pixels':data}))
print(f'Inter: {len(entries)} glyphs, {len(data)} bytes')
