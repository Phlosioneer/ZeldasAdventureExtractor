
from dataclasses import dataclass
from typing import Self

from .struct_stream import StructStream


@dataclass(eq=True, frozen=True)
class Coords:
    """
    Any coordinate position, in pixels, with (0, 0) at the top left.
    """
    x: int
    y: int

    def fromStream(stream: StructStream, xFirst: bool = True) -> Self:
        """Coords are usually stored y first, but sometimes x first."""
        if xFirst:
            x, y = stream.take("hh")
        else:
            y, x = stream.take("hh")
        
        return Coords(x, y)
    
    def __repr__(self):
        return "({}, {})".format(self.x, self.y)


# eq + frozen allows this to be a dictionary key
@dataclass(eq=True, frozen=True)
class ActorDescLocation:
    """
    Describes an actor description's location in a way that can be saved
    to a json file.
    
    Used for the spriteNames.json file.
    """

    # True if the cell is in the `over.rtf` file, false if it's in `under.rtf`
    isOverworld: bool
    cell: str
    # The index of this description in the cell's actor description array.
    index: int


@dataclass
class BoundingBox:
    minX: int | None = None
    maxX: int | None = None
    minY: int | None = None
    maxY: int | None = None
    
    def add(self, coords):
        if isinstance(coords, list):
            for p in coords:
                self.add(p)
            return
        elif isinstance(coords, Coords):
            x = coords.x
            y = coords.y
        elif isinstance(coords, tuple):
            x = coords[0]
            y = coords[1]
    
        if self.minX == None:
            self.minX = x
            self.maxX = x
            self.minY = y
            self.maxY = y
        else:
            self.maxX = max(self.maxX, x + 3)
            self.minX = min(self.minX, x - 2)
            self.maxY = max(self.maxY, y + 3)
            self.minY = min(self.minY, y - 2)

    def width(self):
        return self.maxX - self.minX
    
    def height(self):
        return self.maxY - self.minY
