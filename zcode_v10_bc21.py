"""BC-21 series sample built on the user-approved plate background.

Same pipeline as zcode_v10_rebuild.py: the user's chosen background plate,
brand-blue recoloured vector groups cropped from the source, and the
transparent Kangsheng title block.  Group boxes in display coordinates were
measured from the source (rotation 270 view) by region growing; target rects
preserve each group's aspect ratio.
"""
from pathlib import Path
import csv, re, sys
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
from pypdf import PdfReader

ROOT=Path('/Users/vill/Documents/Codex/2026-09-17/referenced-chatgpt-conversation-this-is-an')
SRC=Path('/Users/vill/Downloads/BC-21系列塑高2.25H Model.pdf')
OUT_DIR=ROOT/'outputs'/'ZCode_V10'
OUT=OUT_DIR/SRC.name
BG=ROOT/'work'/'zcode_v10_background.png'
TITLE=ROOT/'work'/'titleblock_bc21.png'
PLATE=ROOT/'work'/'user_bg_plate.png'
sys.path.insert(0,str(ROOT/'work'))
from titleblock_factory import make_titleblock
BRAND=ROOT/'work'/'approved_brand_strip_with_dot.png'

BLUE=(6/255,66/255,168/255)
GOLD=(230/255,162/255,26/255)

def font(size, bold=False):
    try:return ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',size,index=1 if bold else 0)
    except Exception:return ImageFont.load_default()

def cjk(size):
    return ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',round(size),index=2)

def make_titleblock_v21(model='BC-21系列塑高2.25mm'):
    """Transparent Kangsheng title block; model text auto-fits its cell."""
    S=3; w,h=422,114; W,H=w*S,h*S
    im=Image.new('RGBA',(W,H),(0,0,0,0));d=ImageDraw.Draw(im,'RGBA')
    blue=(6,66,168)
    def line(xy,wd=1): d.line(tuple(v*S for v in xy),fill=blue,width=wd*S)
    def rect(xy,wd=1): d.rectangle(tuple(v*S for v in xy),outline=blue,width=wd*S)
    def text(x,y,s,f,anchor=None): d.text((x*S,y*S),s,fill=blue,font=f,anchor=anchor)
    f6=font(6*S); f7=font(7*S); f8=font(8*S)
    b,bh=88,43
    rect((b,0,w,bh)); rect((0,bh,b,h)); rect((b,bh,w,h))
    # brand strip, near-white background lifted to transparency
    brand_src=Image.open(BRAND).convert('RGB').crop((40,4,585,78))
    brand=brand_src.resize(((w-b-4)*S,bh*S),Image.Resampling.LANCZOS)
    ba=np.asarray(brand).astype(int)
    edge=np.concatenate([ba[:2].reshape(-1,3),ba[-2:].reshape(-1,3)])
    bgc=np.median(edge,axis=0)
    alpha=(np.clip((np.abs(ba-bgc).sum(axis=2)-20)/50,0,1)*255).astype('uint8')
    brand=Image.fromarray(np.dstack([ba,alpha]),'RGBA')
    im.paste(brand,((b+2)*S,0),brand)
    rect((b,0,w,bh))
    # tolerances
    text(4,47,'UNLESS OTHERWISE',f6); text(4,54,'SPECIFIED, TOLERANCE:',f6)
    text(10,63,'X.      ±0.35',f6); text(10,72,'X.X     ±0.25',f6)
    text(10,81,'X.XX    ±0.15',f6); text(10,90,'X.XXX   ±0.05',f6)
    text(10,100,'ANGULAR ±4°',f6)
    # upper rows
    line((b,60,288,60)); line((b,77,w,77))
    for x in (141,200,232,288): line((x,bh,x,77))
    text(92,47,'DESIGN',f7); text(204,47,'DATE',f7); text(292,47,'TITLE:',f7)
    text(92,64,'APPROVED',f7); text(204,64,'DATE',f7)
    text(355,63,'电池连接器',cjk(11*S),anchor='mm')
    # merged model cell (PART NO row folded in)
    line((b,95,141,95)); line((239,95,w,95))
    for x in (141,239,261,291,331,365,399): line((x,77,x,95))
    text(243,82,'REV:',f7); text(295,82,'SCALE:',f7); text(335,82,'3:1',f8)
    text(369,82,'UNIT:',f7); text(403,82,'mm',f7)
    # lower row
    for x in (141,239,270,301,342,377): line((x,95,x,h))
    text(92,104,'MODEL:',f6); text(243,100,'SIZE:',f7); text(274,100,'A4',f8)
    text(305,100,'SHEET:',f7); text(346,100,'1/1',f8)
    cx,cy=389*S,104.5*S
    d.ellipse((cx-7*S,cy-7*S,cx+7*S,cy+7*S),outline=blue,width=1*S)
    d.ellipse((cx-3*S,cy-3*S,cx+3*S,cy+3*S),outline=blue,width=1*S)
    d.line((cx-9*S,cy,cx+9*S,cy),fill=blue,width=1*S)
    d.line((cx,cy-9*S,cx,cy+9*S),fill=blue,width=1*S)
    d.polygon([(404*S,98*S),(418*S,101*S),(418*S,108*S),(404*S,111*S)],outline=blue)
    # model text: largest W6 size that fits the cell with 4pt side margins
    for pt in (9.5,9,8.5,8,7.5):
        f=cjk(pt*S)
        box=d.textbbox((0,0),model,font=f)
        if (box[2]-box[0])/S <= (239-141-8):
            d.text((190*S,95.5*S),model,fill=blue,font=f,anchor='mm')
            break
    im.save(TITLE)

def make_layout_background(display_w=841.89,display_h=595.276,S=3,rev_table=True,out_path=None):
    W,H=round(display_w*S),round(display_h*S)
    im=Image.open(PLATE).convert('RGB').resize((W,H),Image.Resampling.LANCZOS).convert('RGBA')
    P=lambda pts:[(round(x*S),round(y*S)) for x,y in pts]
    d=ImageDraw.Draw(im,'RGBA');blue=(6,66,168,255)
    def line(coords,fill=blue,width=1):
        d.line(tuple(round(v*S) for v in coords),fill=fill,width=max(1,round(width*S)))
    def rect(coords,fill=blue,width=1):
        d.rectangle(tuple(round(v*S) for v in coords),outline=fill,width=max(1,round(width*S)))
    def txt(x,y,s,sz=9):
        d.text((round(x*S),round(y*S)),s,fill=blue,font=font(round(sz*S)),anchor='mm')
    rect((22,29,820,564),width=1.45)
    long_x=[113.5,224.4,331.8,447.8,554.5,661.8,770.8]
    short_x=[67.8,155.9,267.7,384.0,491.3,598.0,705.4]
    for x in long_x:
        line((x,14,x,29)); line((x,564,x,580))
    for x in short_x:
        line((x,22,x,29)); line((x,564,x,573))
    centers=[75,181,280,396,503,610,716]
    for i,x in enumerate(centers,1):
        txt(x,14.5,str(i),9);txt(x,574.0,str(i),9)
    main_y=[28.8,132.5,236.9,342.9,450.6,564.0]
    short_y=[78.4,181.0,286.5,390.8,498.6]
    for y in main_y[1:-1]:
        line((10,y,22,y));line((820,y,832,y))
    for y in short_y:
        line((15,y,22,y));line((820,y,827,y))
    for letter,y in zip('ABCDE',[(main_y[i]+main_y[i+1])/2 for i in range(5)]):
        txt(15.0,y,letter,10);txt(827.5,y,letter,10)
    if rev_table:
        rx=[563.6,591.3,701.4,734.6,820.0];ry=[28.8,42.3,54.1,66.5]
        rect((rx[0],ry[0],rx[-1],ry[-1]))
        for x in rx[1:-1]:line((x,ry[0],x,ry[-1]))
        for y in ry[1:-1]:line((rx[0],y,rx[-1],y))
        txt(577.4,35.5,'REV.',7.2);txt(646.3,35.5,'DESCRIPTION',7.0)
        txt(718.0,35.5,'DRAW.',7.0);txt(777.3,35.5,'DATE.',7.0)
    out=im.convert('RGB').rotate(-90,expand=True)
    out.save(out_path or BG,quality=95,optimize=True)
    return im.convert('RGB')

def show_component(dst,source_svg,src_display,dst_display):
    x0,y0,x1,y1=map(float,src_display);w=x1-x0;h=y1-y0
    cropped=re.sub(
        r'width="[^"]+" height="[^"]+" viewBox="[^"]+"',
        f'width="{w}" height="{h}" viewBox="{x0} {y0} {w} {h}"',
        source_svg,count=1)
    svg_doc=fitz.open(stream=cropped.encode('utf-8'),filetype='svg')
    component=fitz.open('pdf',svg_doc.convert_to_pdf())
    t=fitz.Rect(dst_display)*dst.derotation_matrix
    dst.show_pdf_page(t,component,0,rotate=270,keep_proportion=False,overlay=True)
    component.close();svg_doc.close()

def place(src_box, center, max_w, max_h):
    """Aspect-preserving target rect centred on `center` inside max box."""
    x0,y0,x1,y1=src_box; sw,sh=x1-x0,y1-y0
    sc=min(max_w/sw,max_h/sh)
    w,h=sw*sc,sh*sc
    return (center[0]-w/2, center[1]-h/2, center[0]+w/2, center[1]+h/2)

def main():
    OUT_DIR.mkdir(parents=True,exist_ok=True)
    make_titleblock('BC-21系列塑高2.25mm', TITLE)   # frozen frame, value swapped
    make_layout_background()
    src=fitz.open(SRC);sp=src[0]
    sp.set_rotation(270)          # content is drawn sideways; view landscape
    out=fitz.open();p=out.new_page(width=sp.mediabox.width,height=sp.mediabox.height)
    p.set_cropbox(sp.cropbox);p.set_rotation(sp.rotation)
    p.insert_image(p.cropbox,filename=str(BG),keep_proportion=False,overlay=False)

    source_svg=sp.get_svg_image(matrix=fitz.Matrix(1,1),text_as_path=True)
    source_svg=source_svg.replace('<svg ','<svg fill="#0642a8" ',1)
    source_svg=(source_svg.replace('#000000','#0642a8')
                           .replace('#00ffff','#e6a21a')
                           .replace('#808080','#6f9bcf'))

    groups=[  # (src display box, target center, max w, max h)
        ((78,47,177,171),  (150,125), 110,115),   # G1 top front view
        ((281,45,441,179), (360,125), 150,125),   # G2 isometric
        ((589,45,821,182), (690,148), 250,150),   # G3 specifications
        ((45,210,219,344), (132,262), 140,120),   # G4 side view
        ((225,204,412,354),(297,270), 170,148),   # G5 section view
        ((444,238,540,311),(470,272), 100,88),    # G6 small end view
        ((595,204,772,435),(150,440), 135,187),   # G7 PCB layout + caption
        ((52,357,204,539), (320,425), 125,140),   # G8 front view DIM A/B
        ((253,420,438,528),(690,330), 212,124),   # G9 PART NO table
    ]
    for box,c,mw,mh in groups:
        show_component(p,source_svg,box,place(box,c,mw,mh))

    title_display=fitz.Rect(400,450,820,564)
    p.insert_image(title_display*p.derotation_matrix,filename=str(TITLE),rotate=270,
                   keep_proportion=False,overlay=True)

    if OUT.exists():OUT.unlink()
    out.save(OUT,garbage=4,deflate=True,clean=False)
    out.close();src.close()

    ri,ro=PdfReader(str(SRC)),PdfReader(str(OUT));pi,po=ri.pages[0],ro.pages[0]
    size_i=(round(float(pi.mediabox.width),4),round(float(pi.mediabox.height),4))
    size_o=(round(float(po.mediabox.width),4),round(float(po.mediabox.height),4))
    status='PASS' if size_i==size_o else 'FAIL'
    q=OUT_DIR/'QC_bc21.csv'
    with q.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f)
        w.writerow(['文件名','原页面尺寸','输出页面尺寸','原rotation','输出rotation','状态'])
        w.writerow([SRC.name,size_i,size_o,int(pi.get('/Rotate',0) or 0),
                    int(po.get('/Rotate',0) or 0),status])
    print(status,OUT)

if __name__=='__main__':main()
