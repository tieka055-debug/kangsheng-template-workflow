"""Standalone rebuild of the fitted-background (Image 2.5 target) sample.

Isolated from the parallel session's outputs: everything lands in
outputs/ZCode_V10/ so the two pipelines never overwrite each other.
Pipeline (placements, CAD gold labels, title block PNG) mirrors the current
make_single_sample_v3.py; only the background field differs: the procedural
quadratic+corner model fitted from the user's approved target image.
"""
from pathlib import Path
import csv, re
import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np
from pypdf import PdfReader

ROOT=Path('/Users/vill/Documents/Codex/2026-09-17/referenced-chatgpt-conversation-this-is-an')
SRC=Path('/Users/vill/Downloads/图纸/BC-60-2P全贴.pdf')
OUT_DIR=ROOT/'outputs'/'ZCode_V10'
OUT=OUT_DIR/SRC.name
BG=ROOT/'work'/'zcode_v10_background.png'
TITLE=ROOT/'work'/'single_sample_titleblock.png'
PLATE=ROOT/'work'/'user_bg_plate.png'

BLUE=(6/255,66/255,168/255)
GOLD=(230/255,162/255,26/255)
COLOR_RE=re.compile(rb"([-+]?(?:\d*\.\d+|\d+))\s+([-+]?(?:\d*\.\d+|\d+))\s+([-+]?(?:\d*\.\d+|\d+))\s+(RG|rg)\b")

def recolor(m):
    rgb=tuple(round(float(m.group(i)),4) for i in range(1,4));op=m.group(4)
    if rgb in {(0.,0.,0.),(0.,1.,0.)}:
        return b'0.043137 0.274510 0.592157 '+op
    if rgb in {(0.,1.,1.),(1.,1.,0.),(1.,0.,0.),(1.,0.,1.)}:
        return b'0.839216 0.631373 0.227451 '+op
    return m.group(0)

def font(size, bold=False):
    try:return ImageFont.truetype('/System/Library/Fonts/Helvetica.ttc',size,index=1 if bold else 0)
    except Exception:return ImageFont.load_default()

def make_layout_background(display_w=841.89,display_h=595.276,S=3):
    W,H=round(display_w*S),round(display_h*S)
    # The user's chosen background plate, used verbatim: its diagonal light
    # bands and icy-blue washes ARE the design. Only the drawing frame,
    # zone ticks and REV table are drawn on top.
    im=Image.open(PLATE).convert('RGB').resize((W,H),Image.Resampling.LANCZOS).convert('RGBA')
    P=lambda pts:[(round(x*S),round(y*S)) for x,y in pts]
    d=ImageDraw.Draw(im,'RGBA');blue=(6,66,168,255)
    def line(coords,fill=blue,width=1):
        d.line(tuple(round(v*S) for v in coords),fill=fill,width=max(1,round(width*S)))
    def rect(coords,fill=blue,width=1):
        d.rectangle(tuple(round(v*S) for v in coords),outline=fill,width=max(1,round(width*S)))
    def txt(x,y,s,sz=9,bold=False,anchor=None):
        f=font(round(sz*S),bold)
        d.text((round(x*S),round(y*S)),s,fill=blue,font=f,anchor=anchor)
    rect((22,29,820,564),width=1.45)
    long_x=[113.5,224.4,331.8,447.8,554.5,661.8,770.8]
    short_x=[67.8,155.9,267.7,384.0,491.3,598.0,705.4]
    for x in long_x:
        line((x,14,x,29)); line((x,564,x,580))
    for x in short_x:
        line((x,22,x,29)); line((x,564,x,573))
    centers=[75,181,280,396,503,610,716]
    for i,x in enumerate(centers,1):
        txt(x,14.5,str(i),9,anchor='mm');txt(x,574.0,str(i),9,anchor='mm')
    main_y=[28.8,132.5,236.9,342.9,450.6,564.0]
    short_y=[78.4,181.0,286.5,390.8,498.6]
    for y in main_y[1:-1]:
        line((10,y,22,y));line((820,y,832,y))
    for y in short_y:
        line((15,y,22,y));line((820,y,827,y))
    for letter,y in zip('ABCDE',[(main_y[i]+main_y[i+1])/2 for i in range(5)]):
        txt(15.0,y,letter,10,anchor='mm');txt(827.5,y,letter,10,anchor='mm')
    rx=[563.6,591.3,701.4,734.6,820.0];ry=[28.8,42.3,54.1,66.5]
    rect((rx[0],ry[0],rx[-1],ry[-1]),width=1)
    for x in rx[1:-1]:line((x,ry[0],x,ry[-1]))
    for y in ry[1:-1]:line((rx[0],y,rx[-1],y))
    txt(577.4,35.5,'REV.',7.2,anchor='mm')
    txt(646.3,35.5,'DESCRIPTION',7.0,anchor='mm')
    txt(718.0,35.5,'DRAW.',7.0,anchor='mm')
    txt(777.3,35.5,'DATE.',7.0,anchor='mm')
    out=im.convert('RGB').rotate(-90,expand=True)
    out.save(BG,quality=95,optimize=True)
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

def overlay_cad_label_paths(dst,src,regions,dx,dy):
    selected=0
    for drawing in src.get_drawings():
        display_box=drawing['rect']*src.rotation_matrix
        if not any(r.contains(display_box) for r in regions):
            continue
        if display_box.width>9 or display_box.height>8:
            continue
        shape=dst.new_shape()
        for item in drawing['items']:
            if item[0] != 'l':
                continue
            a=item[1]*src.rotation_matrix
            b=item[2]*src.rotation_matrix
            a=fitz.Point(a.x+dx,a.y+dy)*dst.derotation_matrix
            b=fitz.Point(b.x+dx,b.y+dy)*dst.derotation_matrix
            shape.draw_line(a,b)
        stroke=max(1.05,float(drawing.get('width') or .72)*1.25)
        shape.finish(color=GOLD,width=stroke,lineCap=0,lineJoin=0)
        shape.commit(overlay=True)
        selected+=1
    return selected

def main():
    OUT_DIR.mkdir(parents=True,exist_ok=True)
    bg_display=make_layout_background()
    src=fitz.open(SRC);sp=src[0]
    out=fitz.open();p=out.new_page(width=sp.mediabox.width,height=sp.mediabox.height)
    p.set_cropbox(sp.cropbox);p.set_rotation(sp.rotation)
    p.insert_image(p.cropbox,filename=str(BG),keep_proportion=False,overlay=False)

    source_svg=sp.get_svg_image(matrix=fitz.Matrix(1,1),text_as_path=True)
    source_svg=source_svg.replace('<svg ','<svg fill="#0642a8" ',1)
    source_svg=(source_svg.replace('#000000','#0642a8')
                           .replace('#00ffff','#e6a21a')
                           .replace('#808080','#6f9bcf'))

    placements=[
        ((123,102,215,171),(100,80,192,149)),       # top front
        ((342,79,474,187),(312,72,444,180)),        # isometric
        ((97,234,216,358),(75,200,194,324)),        # middle left
        ((252,222,403,363),(215,190,366,331)),      # middle side
        ((402,234,519,353),(415,210,532,329)),      # middle right
        ((110,395,270,483),(300,360,460,448)),      # lower end view
        ((578,213,739,385),(90,345,251,517)),       # PCB layout + note
        ((546,34,802,194),(563,79,819,239)),        # specifications
        ((338,372,576,450),(573,266,811,344)),      # model/dimension table
    ]
    for s,t in placements:show_component(p,source_svg,s,t)

    label_count=overlay_cad_label_paths(
        p,sp,
        [fitz.Rect(211,456,242,470),fitz.Rect(236,440,266,454)],
        dx=190,dy=-35)
    if label_count != 11:
        raise RuntimeError(f'DIM label path detection expected 11, got {label_count}')

    title_display=fitz.Rect(400,450,820,564)
    p.insert_image(title_display*p.derotation_matrix,filename=str(TITLE),rotate=270,
                   keep_proportion=False,overlay=True)

    if OUT.exists():OUT.unlink()
    out.save(OUT,garbage=4,deflate=True,clean=False)
    out.close();src.close()

    ri,ro=PdfReader(str(SRC)),PdfReader(str(OUT));pi,po=ri.pages[0],ro.pages[0]
    size_i=(round(float(pi.mediabox.width),4),round(float(pi.mediabox.height),4))
    size_o=(round(float(po.mediabox.width),4),round(float(po.mediabox.height),4))
    rot_i=int(pi.get('/Rotate',0) or 0);rot_o=int(po.get('/Rotate',0) or 0)
    status='PASS' if size_i==size_o and rot_i==rot_o else 'FAIL'
    q=OUT_DIR/'QC.csv'
    with q.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f);w.writerow(['文件名','原页面尺寸','输出页面尺寸','原rotation','输出rotation','状态'])
        w.writerow([SRC.name,size_i,size_o,rot_i,rot_o,status])
    print(status,OUT)

if __name__=='__main__':main()
