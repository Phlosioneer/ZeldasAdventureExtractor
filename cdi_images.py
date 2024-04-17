import PIL.Image
import array
from struct_stream import StructStream
import struct

QUANT_TABLE = [
          0,   1,   4,   9,
         16,  27,  44,  79,
        128, 177, 212, 229,
        240, 247, 252, 255
    ]

def to_yuv422p(data, width, height, startValues):
    
    # Adapted from https://github.com/roysmeding/cditools/blob/rewrite/cdi/formats/dyuv.py#L28
    Y = array.array('B', (0 for _ in range(width * height     )))
    U = array.array('B', (0 for _ in range(width * height // 2)))
    V = array.array('B', (0 for _ in range(width * height // 2)))

    for y in range(height):
        if isinstance(startValues, list) and isinstance(startValues[0], tuple):
            Yprev, Uprev, Vprev = startValues[y]
        else:
            Yprev, Uprev, Vprev = startValues

        for x in range(0, width, 2):
            idx = y * width + x
            B0, B1 = struct.unpack('BB', data[idx:idx + 2])

            dU, dY0 = (B0 & 0xF0) >> 4, B0 & 0x0F
            dV, dY1 = (B1 & 0xF0) >> 4, B1 & 0x0F

            Yprev = (Yprev + QUANT_TABLE[dY0]) & 0xFF
            Y[idx] = Yprev

            Yprev = (Yprev + QUANT_TABLE[dY1]) & 0xFF
            Y[idx + 1] = Yprev

            Uprev = (Uprev + QUANT_TABLE[dU ]) & 0xFF
            U[idx // 2] = Uprev

            Vprev = (Vprev + QUANT_TABLE[dV ]) & 0xFF
            V[idx // 2] = Vprev
    return Y, U, V

def to_yuv444p(data, width, height, startValues):
    Y, U, V = to_yuv422p(data, width, height, startValues)

    Uout = array.array('B', (0 for _ in range(width * height)))
    Vout = array.array('B', (0 for _ in range(width * height)))

    for y in range(height):
        for x in range(0, width, 2):
            idx = y * width + x

            Uout[idx] = U[idx // 2]
            if x < width - 2:
                Uout[idx + 1] = (U[idx // 2] + U[(idx // 2) + 1]) // 2
            else:
                Uout[idx + 1] =  U[idx // 2]

            Vout[idx] = V[idx // 2]
            if x < width - 2:
                Vout[idx + 1] = (V[idx // 2] + V[(idx // 2) + 1]) // 2
            else:
                Vout[idx + 1] =  V[idx // 2]

    return Y, Uout, Vout
    
def dyuvToRGB(data, width, height, startValues):
    Y, U, V = to_yuv444p(data, width, height, startValues)
    # def to_pil(self):
    def _interleave():
        for i in range(len(Y)):
            yield Y[i]
            yield U[i]
            yield V[i]

    return PIL.Image.frombytes('YCbCr', (width, height), bytes(_interleave())).convert('RGB')

# Sane defaults
def dyuvToRGBBackground(data):
    return dyuvToRGB(data, 384, 240, (0x80, 0x80, 0x80))

def clut8ToRGB(data, width, height, palette):
    image = PIL.Image.frombytes("P", (width, height), data)
    image.putpalette(palette)
    return image

def rl7ToRGB(data, palette:bytes, transparentColor = None, emptySpaceColorIndex = 0, forceWidth = None):
    assert isinstance(palette, bytes)
    lastNonzeroIndex = 0
    for i, b in enumerate(data):
        if b != 0:
            lastNonzeroIndex = i
    #print(lastNonzeroIndex, len(data))
    truncImageData = data[:lastNonzeroIndex + 2]

    i = 0
    pixelRows = []
    currentRow = b''
    while i < len(truncImageData):
        if truncImageData[i] & 0x80 == 0:
            #print("single")
            currentRow += truncImageData[i].to_bytes(1)
            i += 1
        elif truncImageData[i + 1] == 0:
            pixelRows.append(currentRow)
            currentRow = b''
            i += 2
        else:
            c = (truncImageData[i] & 0x7F).to_bytes(1)
            for _ in range(truncImageData[i + 1]):
                currentRow += c
            i += 2
    if len(currentRow) != 0:
        print("Warning: last row had data")
        pixelRows.append(currentRow)
    del currentRow
    del i

    if forceWidth == None:
        width = max([len(r) for r in pixelRows])
    else:
        width = forceWidth
    height = len(pixelRows)
    pixels = b''
    for row in pixelRows:
        pixels += row 
        for _ in range(width - len(row)):
            pixels += emptySpaceColorIndex.to_bytes(1)
    assert len(pixels) == width * height

    if len(pixels) == 0:
        print("Empty frame")
        ret = PIL.Image.frombytes('P', (1, 1), b'\0')
        ret.putpalette(b'\0\0\0\0', rawmode = "RGBA")
        return ret

    img = PIL.Image.frombytes('P', (width, height), pixels)

    
    rgbaPalette = b''
    i = 0
    while i < len(palette):
        c = palette[i:i + 3]
        rgbaPalette += c
        if c == transparentColor:
            rgbaPalette += b'\0'
        else:
            rgbaPalette += 0xFF.to_bytes(1)
        i += 3
    img.putpalette(rgbaPalette, rawmode="RGBA")
    return img
