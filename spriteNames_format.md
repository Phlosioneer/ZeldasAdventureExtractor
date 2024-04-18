
# Purpose

Zelda's Adventure stores entities on a per-cell (aka screen) basis. There is nothing in the game, the code, or the metadata to "link" or correlate all the keese in every
cell.

This file fills that role, so that you can ask questions like "Which screens have
keese?" and "Do all keese have the same stats?"

# Definitions

- **Actor Instance**: A particular NPC in a specific cell.
- **Actor Definition** (aka Actor Description): A kind or group of identical NPCs in a specific cell. All *Actor Instances* belong to an *Actor Definition*, even if it's only used once.
- **Actor Variant**: All *Actor Definitions* that share sprites.
- **Global Actor**: All *Actor Definitions* that people would call the 'same', but they don't actually have bit-for-bit identical sprites.

# Naming Convention

*Global Actors* are named with categories. Later dots get more specific. Something like `<category>.<name>.<subtype>`. Enemy's projectiles are grouped with the enemy with a `.projectile` subtype.

# Manual Editing: Change a Name

If you want to rename an NPC, find their current name, do Find & Replace with their new name, and that's it. The Find & Replace will ensure that you get all the `name` fields on each variant.

# File Layout

The root object is a map from *Global Actors* to an array of their variants. Each variant has:
- `hash`: A hash of all of its sprites
- `name`: The name of the *Global Actor* that this variant represents
- `spriteGroups`: Unused, side-effect of the automatic generation of the file. Safe to ignore or remove.
- `mainLocation`: The first cell where this enemy appears. Usually just the first entry of `locations`. See below for the location object format.
- `locations`: An array of locations where this variant is used. Each location has:
    - `cell`: The name of the cell in the `.rtf` file.
    - `isOverworld`: If true, the cell is in `over.rtf`, otherwise the cell is in `under.rtf`
    - `descIndex`: The index in the cell's *Actor Description* array.