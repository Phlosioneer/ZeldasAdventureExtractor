
# General Patterns

## Scripts that have code for red boots, but don't use it
These scripts have code for allowing zelda to walk on the water using the red boots. But the trigger area for that is missing; the water uses unconditional collision.

Cells: C8, D8, E8, E9, E10, G10, H11, I11, J11, J17, K12, K16, K17, K18, L12, L15, L16, M12, M13, M14, M15, N12, N13, N14, O10, O12, O14, P8, P9, pP0, P14, Q14, R16

## Scripts with conditional checks in the wrong order
Conditional script actions can affect later conditional checks. Several cells have dialogue or other actions that are intended to happen in sequence. The checks are written in logical order, but that means each check sets up a local variable for the next check. Here's an example:

```py
if local0 == 0:
    nextVoiceLine = line0
    local0 = 1

if local0 == 1:
    nextVoiceLine = line1
    local0 = 2

if local0 == 2:
    # etc
```

In the example, all the conditional script actions execute in one frame, and each voice line command overwrites the previous one. Only the last voice line will actually play.

Cells:
- K13a: Shopkeeper skips line #4
- K13b: Madame Kriggle skips line #1 and #2
- K14: Town Merchant skips line #7
- L14: The Twins skip line #1
- L14a: The actor skips line #1
- L27a: Toobar skips line #1
- U16: The merchant skips line #1, #2, and #3.

## Items that can be left in a "dropped" state.
Items in your inventory can be absent (0), present (1), or "dropped" (2). When in the dropped state, they're in the world waiting for you to pick them up.

Conditional checks for items *may* not take this third state into account. For any such scripts, you can skip picking up the item; having it appear on screen is sufficient.

Items that use this dropped state are:
- Boomerang, d24
- FullWaterBottle, e20
- Pyros, j15
- Firestorm, j22
- Dagger, j22a
- Vial of Winds, j24
- Diamond, l13
- Flute, l14

## Raft Mechanics
The scripting system doesn't have any way to tell a raft to start going. It starts on its path immediately after spawning, if it has a path. That path is also not reversible or adjustable, though the actor can be left on screen after it's done moving.

To get around these limitations, there are multiple raft actors; usually one that is stationary, one that goes left, and one that goes right. When zelda touches a stationary raft, it despawns itself and spawns the moving raft. When zelda enters the screen, she's placed on a raft according to the `RAFT_JOURNEY_STATE` variable's value.

The `RAFT_JOURNEY_STATE` values for each raft ride are:

- L28 to Q28: 
    - `0` for not started / done
    - `1` if going towards the shrine
    - `2` if going away from the shrine

## The Alligator Shoes

The vendoss swamp has many cells where the code checks for alligator shoes. If the player doesn't have any alligator shoes, trigger color areas are impassible, but with them, movement speed is halved (movement type 4). However, alligator shoes were cut from the game. Only one cell with the alligator shoe code has a trigger color area (V18) but it cannot be reached without triggering the load zone.

Weirdly, on some cells, the alligator shoe logic uses full speed movement (0) instead of half speed movement (4).

Half Speed Cells: Q18, R17, R18, R19, R20, S19, S20, T16, T19, T20, U19, U20, V17, V18, V19

Full Speed Cells: Q19, S15, S16, T14, T15, U14, U15, U16, U17, V15, W15, W16

## Repellent
Having the repellent item in your inventory prevents swamp zolas from spawning. The checks test for item absence, but unfortunately the repellent item never enters the "dropped" state, so that can't be exploited.

Cells: R17, R18, S16, T15, T16

## Cell Coordinate Format
Wherever cell coordinates are specified in scripts (setting the UP/DOWN/RIGHT/LEFT neighbors, and in teleportation commands), they follow a common format. The first byte is usually `\0` (the null byte); this would be the easiest way to store the data if they were stored one word at a time. The coordinate string follows as normal. Large strings may
use the first byte.

The first five bytes of the string are used for cell lookup. The 6th byte does not seem to be used by the game. However, it is always either `f` or `s`, depending on the screen transition. `f` means fade in/fade out, while `s` means scroll. The game actually uses the direction system to determine scrolling strategy.

## Unused movement type 2

Some cells feature an unused movement type return value for color trigger areas. Type 0 blocks movement, Type 1 is normal movement, Type 2 is unimplemented, Type 3 is unimplemented, and Type 4 is half-speed movement.

None of these cells have any color trigger areas, so the code for this type is never executed. Which doesn't matter, because there isn't any code; it just acts like normal movement.

Cells: S101a, H27, S119

# Specific Cells

## D24
This is the boomerang cave. When the first goriya dies, it increments a counter. When the second one dies, it directly spawns the boomerang. It also allows the boomerang to spawn in the future, if zelda leaves and re-enters before picking it up.

It allows the persistent boomerang spawn by setting the player's BOOMERANG variable to 2. If anything checks for the boomerang using `save[BOOMERANG] != 0`, it will be fooled by this, and zelda would never have to pick up the item.

Saving and re-loading the game will clear the BOOMERANG variable back to 0. Only the least significant bit is saved when compressing.

## F22
F22 has local variables with the cell name for P15. Prehaps they were once connected?

## F28
The ladder item checks both zelda's inventory and the ladder-placement variable when deciding whether to spawn. But the ladder is never removed from zelda's inventory, so the check is useless.

## G11
Pressing and holding the Diamond item until it's been used 100 times causes Food Dude to appear on screen.

## G23
The overworld spawn cell has a `setLocationOnMap(g22)` line, which is weird.

## H23
H23 has local variables with the cell name for G30. Perhaps they were once connected?

There's also an unused local variable set to `1`.

# H29: The Hag
When the player enters the screen, if `HAG_INTERACT_DONE` global is set to 0, the Hag and her campfire spawn.

When the player touches the hag *after* she is done speaking her first line, she takes one heart from Zelda, then talks. After talking, the `HAG_INTERACT_DONE` global is set to 1.

When she is hit by zelda before being touched (or while she is speaking her first line), she disappears with a sparkle animation, then talks, and the `HAG_INTERACT_DONE` global is set to 1 immediately. However, hitting NPCs was disabled, so this code is unreachable.

## J15
If the player doesn't have Pyros, a rope (aka snake) is spawned. When killed, it spawns six fire sprites and the pyros item. Pyros is put in the special "dropped" state in the player's inventory. The rope has 5 health, but it has 500 defense and no weaknesses, so it cannot be killed.

The pyros item is triggered when the flute is used. It then freezes the player while the flute plays. When the sound ends, it destroys the rope and unfreezes the player.

**The pyros onItemInteractOrSoundFileDone trigger works correctly even while the pyros item's sprite has not spawned.**

**The rope's onDeath trigger is called when another actor's script despawns it.**

## J17
When one farmer has been touched, they speak. After speaking, they despawn, and spawn a second farmer. They do the same with a third farmer. After speaking with the third farmer, they don't despawn.

## J21a
Instead of using the usual INDOOR_ID variable, this cell uses zelda's facing direction to determine where she entered from.

## J22
The variable `local3` means "isBeggarInteractable".

BUG: The script does not check if zelda has enough rupees.

BUG: The script does not prevent the player from using the Rupee item in the middle of the beggar's voice line. Extra rupees are paid, and firestorm can be spawned after picking it up, but nothing interesting happens.

## J22a
The variable `local9` means "isSomeoneTalking". Then each actor has a local variable indicating how many times they've talked.

The tired traveller will only speak their second line if you don't have the Calm spell.

There's a candle actor with the code to be sold, but it never spawns. It doesn't have a price set, and it doesn't have the sprite for a price. The ordering of the actors suggests that it would have been sold by the tired traveller.

## J24: Glebb the Thirsty
Glebb has code to hit zelda back if she is attacked. But damaging NPCs was removed from the game, so this is unreachable.

When the player uses the full water bottle, the vial of winds removes the full water bottle from the player's inventory, and plays a line. After the line, it spawns itself. If the player leaves the screen before the line completes, the empty water bottle will spawn and they will have to start the quest from the beginning.

## K13
When the lounger loads, they choose to play either line 0 or 4. Then when that line finishes, they try to play line 2. BUT, if the `LOUNGER_LINE_K13` global is not set, that attempt is overwritten with line 1.

The result is two unique lines, 0 and then 1, when you first enter the cell; and two different lines, 4 and then 2, every time after the first.

## K13a
The shopkeeper's line sequence has two bugs. First, the conditional statements should be in descending order. The first conditional statement's body sets the local variable to 2, which is immediately checked by the second conditional statement.

Second, the second line sets the local variable to 2 again, when it should have set it to 3. This causes that line to loop forever. (TODO: Confirm this behavior).

## K20
The silver trumpet actor is unable to spawn. Also, there's an unused local variable 0, which is strange.

## L14
`local7` means "isSomeoneSpeaking".

There's a slight bug in Yvonne's script. When she begins speaking line #4, local7 is not set to 1.

## L28
The raft and sailors won't spawn until the 5th shrine is complete.

The raft starts off to the left side of the screen, and the area to board the raft is blocked by conditional terrain. When zelda uses the vial of winds, the raft as `cast[2]` despawns itself, and spawns a new raft with an animation that takes it to the left. The area to board the raft is unblocked as well. Local0 is set to `1`.

When the raft arrives at the boarding area, local0 is set to `2`. At this point, a animation action executes the OnPurchaseOrAnimationComplete trigger, and despawns the `cast[3]` raft. The trigger spawns the next raft, `cast[4]`. 



The raft has broken "onPurchase" logic. The sailor NPC doesn't use the purchase system, so that trigger never happens. It looks like the developers tried to make it work, but couldn't. The "onPurchase" logic is also incomplete; it doesn't despawn `cast[3]`. 

## M25a

The switch toggles sprite groups whenever hit. But it uses local1 to only spawn the bridge once. The switch only spawns if the heart container hasn't been taken yet.

## M28
The raft on this screen has functionality to go either towards or away from the shrine. It looks like there used to be a return trip, but it was removed.

This screen contains an onRespawn trigger that removes the raft, but doesn't reposition Zelda. Even if enemies were on this screen, the trigger would not be necessary.

## N9
Walking into the great fairy 

## N11
There's a black key on this map, but it is never spawned.

The npc who gives the feather spawns it after speaking one part of his lines, and after zelda has entered the white steed lodge.

## O22
Instead of using the usual INDOOR_ID variable, this cell uses zelda's facing direction to detect when she has been teleported to the cell from the j21a cave.

## O28
When entering the screen, the first raft (`cast[1]`) is spawned. It takes zelda to the center of the screen. When it reaches the center, it increments the local3 variable and spawns the sea monster. When the sea monster dies, it despawns the first raft, and spawns the second raft (`cast[2]`), which then takes zelda to the edge of the screen.

## P15
There's two unused local variables here, local0 and local1. There's also another local variable, local2, with the coordinate for f22. Perhaps they used to be connected by teleport?

## P20a
local4 means "isSomeoneTalking"

There's code for the hourglass, but it's not spawned.

## Q15
The code here tries to prevent the player from paying before Yalzan's line finishes. The first voice line end trigger or item interact increments a local variable, and then the second voice line end trigger or item interact will actually try to do the transaction. However, two uses of the rupee item thwart this. The code should have used the `IS_INTERACT_TRIGGER` variable instead.

Unfortunately, the spikes cannot be circumvented by damage boosting. There's conditional collision covering the gate that only allows walking after paying.

## R9
local3 means "isSomeoneTalking"

## R10
local2 is written but never used. And it's a bit unusual that local1 and local3 are separate.

## S201
The pit actor uses the raft mechanic to move the player in position during the animation.

## S214
TODO: This cell is using RESPAWN_CELL_ID in weird ways that I don't understand.

## S301
The purple bird locks the player out of movement while animating. At the end of its animation, it unlocks the player's movement.

## S401
TODO: This cell is using RESPAWN_CELL_ID in weird ways that I don't understand.

## S415
TODO: This cell is using RESPAWN_CELL_ID in weird ways that I don't understand.

## S613
TODO: This cell is using RESPAWN_CELL_ID in weird ways that I don't understand.


# Names
I have some actor names (or at least abbreviations) from the script data, which I couldn't find anywhere else:
- The goblin on g9 is named "Bik"
- The Wimbich blacksmith on k14 is named "Rowell"
- The waiter in the White Steed Lodge (n11a) is named "Der", and the other standing person is named "Deb"
- The man in brown clothes on p20a is called "Cap", and the woman is called "For". I think Cap is short for Captain. No idea what "For" means.
- The person on z1 is named "Nim"
- There are a lot of people called "Pick", likely meaning "Pickpocket". At least 5 of them.
- The person at the archery minigame is called "Trainer"

last visited: u18