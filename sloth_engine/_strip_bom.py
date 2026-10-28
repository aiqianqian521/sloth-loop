import sys
for p in sys.argv[1:]:
    try:
        b=open(p,'rb').read()
    except OSError:
        continue
    if b.startswith(b'\xef\xbb\xbf'):
        b=b[3:]
        open(p,'wb').write(b)
print('strip_bom:', len(sys.argv)-1, 'files')
