
# Actor Desc Projectile Field

## The Problem

The code only cares about zero or nonzero, and only if the actor is an enemy (type 2).

However, the game data allows 6 different values, and they have some patterns. The allowed values are:

```
00 = 0000_0000
01 = 0000_0001
48 = 0011_0000
49 = 0011_0001
52 = 0011_0100
```

Every item (including cut ones) that can be sold has value 48. One strong piece of evidence for this is the candle cut from the Moblin Inn. It was going to be given to zelda, not sold; and it is the only candle in the game with value 0. 

The only item that breaks the pattern is Vial of Winds, which has value 48 but isn't sold. Perhaps Glebb used to sell it after the water quest was done?

Every enemy that can use projectiles has the bottom bit set (1 or 49), while every projectile has the bottom bit cleared (0, 48, or 52). This strongly suggests the original meaning of the field is a set of bit flags. But I can't think of any possible reason for bits 4 and 5 to always match.

## The Data

```
{data}
```