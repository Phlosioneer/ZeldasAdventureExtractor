from __future__ import annotations

from typing import Literal, Tuple, List, Union, TYPE_CHECKING, TypeVar
from dataclasses import dataclass


import PIL.Image

from struct_stream import StructStream

if TYPE_CHECKING:
    from za_lib import ActorDescription

def decompressSprite(stream: StructStream, palette: bytes, paletteMode: Literal["RGB", "RGBA"]):
    """
    Decompresses zelda sprite storage format.
    
    I don't know how common this format is among CDI games, but people were able
    to figure it out without looking at the decompression code, so I'm guessing
    it's common.
    """
    
    # The sprite starts with the number of bytes to decompress.
    byteCount: int = stream.take("I")

    # Split that data into a separate stream.
    stream = stream.takeFork(byteCount)

    # The data is composed of packets of (skiplen, size) pairs.
    # The packet means "skip `skiplen` bytes, then copy `size * 4` bytes."
    pixels = b''
    while stream.peekRaw(4) != b'\0\0\0\0':
        skip, size = stream.take("HH")
        pixels += b'\0' * skip
        pixels += stream.takeRaw(size * 4)
    
    if len(pixels) == 0:
        # Blank image. PIL doesn't alllow images with a width or height of
        # zero, so return a 1x1 transparent image instead.
        return PIL.Image.frombytes("RGBA", (1, 1), b'\0\0\0\0')

    # The decompression algo is designed for copying straight into a cdi
    # draw buffer. We want a nice, cropped image. Right now, we don't have
    # the context needed to figure out the true intended width, so we make
    # it as thin as possible while preserving the upper left corner.
    #
    # First, pad the bytes to a multiple of the screen width (384).
    partialRow = len(pixels) % 384
    pixels += b'\0' * (384 - partialRow)

    # Then split the image into rows.
    rows = [pixels[i * 384:(i + 1) * 384] for i in range(len(pixels)//384)]

    # Find the longest row, which is the minimum width for the image.
    maxWidth = 0
    for row in rows:
        for i, b in enumerate(row):
            if b != 0:
                maxWidth = max(maxWidth, i)

    # Crop the image and recombine the rows into a single stream.
    trimmedRows = [row[:maxWidth] for row in rows]
    pixels = b''.join(trimmedRows)

    # Finally, output the image with the provided palette.
    img = PIL.Image.frombytes("P", (maxWidth, len(rows)), pixels)
    img.putpalette(palette, paletteMode)
    return img

@dataclass
class PointerArray:
    elements: list
    unusedPointer: int

def unpackPointerArray(stream: StructStream) -> PointerArray:
    """
    Unpacks a pointer array into a list of elements, and an unknown integer.

    I suspect that the unknown three-byte integer is a CRC of the contents of
    the list. CRC's on OS-9 are 3 bytes long. But that's a lot of work to
    validate a hunch that doesn't really matter.
    """
    length, unusedPointer = stream.take("II")
    
    # First get the array of pointers to data regions.
    offsets = [stream.take("I") for _ in range(length)]

    # Then assume the elements are densely packed, so all bytes between pointers
    # belong to one element. Also assume that elements do not overlap, and that
    # no data is deduplicated by sharing pointers. Also assume that the offsets
    # are stored in sorted order.
    #
    # It's a lot of assumptions but it works out.
    elements = [stream.takeFork(offsets[i + 1] - offsets[i]) for i in range(len(offsets) - 1)]
    elements.append(stream.fork())
    return PointerArray(elements, unusedPointer)

def unpackSpriteTree(data: bytes, palette: bytes, paletteMode: Literal["RGB", "RGBA"]) -> PointerArray:
    """
    Unpacks a 3-layer tree of sprites, assigning them to the groups of actor descriptions.
    
    Any unused sprites are returned, preserving their tree structure using nested lists.
    """
    topStream = StructStream(data, endianPrefix=">")
    topArray = unpackPointerArray(topStream)
    
    actorTree: List[StructStream]
    for i, actorTree in enumerate(topArray.elements):
        middleArray = unpackPointerArray(actorTree)
        topArray.elements[i] = middleArray

        groupTree: List[StructStream]
        for j, groupTree in enumerate(middleArray.elements):
            bottomArray = unpackPointerArray(groupTree)
            middleArray.elements[j] = bottomArray

            bottomArray.elements = [decompressSprite(s, palette, paletteMode) for s in bottomArray.elements]
    
    return topArray

def getClut(data: Union[bytes, StructStream]) -> bytes:
    """
    Reads a clut file.

    A clut file starts with a 4-byte color count, followed by that many
    colors. Each color is encoded as three bytes in RGB order. 
    """
    if not isinstance(data, StructStream):
        stream = StructStream(data, endianPrefix=">")
    else:
        stream = data
    size = stream.take("I")
    return stream.takeRaw(size * 3)

def convertClutToRgba(clut: bytes, indices: List[int] = [], tColors: List[bytes] = []) -> bytes:
    """
    Converts a palette from RGB to RGBA.
    
    Colors are made fully transparent if they are in the `tColors` array, or if
    their index is in the `indices` array. Otherwise they are unchanged.
    """
    assert len(indices) > 0 or len(tColors) > 0, "Need to provide indices or colors"
    paletteColors = [clut[i:i+3] for i in range(0, len(clut), 3)]
    for i in range(len(paletteColors)):
        opacity = b'\xFF'
        if i in indices or paletteColors[i] in tColors:
            opacity = b'\0'
        paletteColors[i] = paletteColors[i] + opacity
    return b''.join(paletteColors)