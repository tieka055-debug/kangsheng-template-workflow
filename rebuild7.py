"""Rebuild the 7 already-uploaded rows with the current build_ink pipeline."""
import sys
sys.path.insert(0, '.')
from build_ink import run_ink
import pathlib

DL = '/Users/vill/Downloads/图纸/'
OUT = pathlib.Path('../outputs/ZCode_V10')
ROWS = [
    ('2D_BC-21系列沉板1.25.pdf',         'BC-21系列沉板1.25',  '2D_BC-21系列沉板1.25.pdf',        'row11'),
    ('2D_BC-22系列母座 Model.pdf',       'BC-22系列母座',      '2D_BC-22系列母座 Model.pdf',      'row13'),
    ('2D_BC-16系列1.8H-R1.25 Model.pdf', 'BC-16系列1.8H-R1.25','2D_BC-16系列1.8H-R1.25 Model.pdf','row14'),
    ('2D_BC-16系列1.8H-R1.9 Model.pdf',  'BC-16系列1.8H-R1.9', '2D_BC-16系列1.8H-R1.9 Model.pdf', 'row15'),
    (DL+'BC-16系列2.2H-R1.25.pdf',       'BC-16系列2.2H-R1.25','2D_BC-16系列2.2H-R1.25.pdf',      'row16'),
    (DL+'BC-16系列2.2H-R1.9 Model.pdf',  'BC-16系列2.2H-R1.9', '2D_BC-16系列2.2H-R1.9 Model.pdf', 'row17'),
    (DL+'BC-17系列3-10P.pdf',            'BC-17系列母座',      '2D_BC-17系列3-10P.pdf',           'row18'),
]
if __name__ == '__main__':
    only = sys.argv[1:] or None
    for src, model, outname, tag in ROWS:
        if only and tag not in only:
            continue
        print(tag, outname)
        ok = run_ink(src, str(OUT / outname), model, f'/tmp/qa_{tag}.png')
        assert ok, tag
    print('DONE')
