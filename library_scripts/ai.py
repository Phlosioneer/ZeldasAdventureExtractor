

######################
# Special Syntax and Terminology
#
# Everything in this file refers to "animFrames", short for Animation Frames.
# An animation frame happens once per 60ms +/- 1.2ms, or between 16.3 and 17.2
# times per second. (A particular CDI model picks a time in the range 58.1 to 61.2
# and keeps that time super accurately. See tech node 94, ICDIA website.)
#
# The animation methods below use very-close-to-python syntax.
# To convey animation frame timing, though, the functions could use two
# different methods.
#
# Some functions use the syntax `yield nextAnimFrame()` to mean that *their*
# work for the animation frame is done. Normally this ends the frame, but
# sometimes animations can run in parallel.
#
# Some functions use the syntax `yield from someOtherAnimation()` to 
# mean that someOtherAnimation runs, and the current animation waits for it
# to finish before continuing. `yield` does not count as finishing the animation.
# Switching to an animation this way ALWAYS ends the current frame before the
# next frame starts. 
#
# Some functions (currently only bosses) use the decorator `@AllFunctionsEndTheFrame`.
# Within these functions, EVERY function call is treated as a `yield from ...`
# statement. So for example, this function:
#
# ```
# @AllFunctionsEndTheFrame
# def bossAI():
#	actor.position = { x=112, y=4 }
#	while True:
#		SetAnimationGroup(group=0)
#		SetIsInvulnerable(invulnerable=False)
#		MoveToGoal(x=4, y=4)
#		MoveToGoal(x=112, y=52)
#		WasteOneFrame() # It takes one frame to reset the loop counter.
# ```
#
# Is equivalent to:
#
# ```
# def bossAI():
#	actor.position = { x=112, y=4 }
#	while True:
#		yield from SetAnimationGroup(group=0)
#		yield from SetIsInvulnerable(invulnerable=False)
#		yield from MoveToGoal(x=4, y=4)
#		yield from MoveToGoal(x=112, y=52)
#		yield from WasteOneFrame() # It takes one frame to reset the loop counter.
# ```
#
# Summary:
# - `yield nextAnimFrame()` means end the current frame.
# - `yield from someOtherAnimation()` means to play someOtherAnimation and wait for
#       it to finish.
# - `yield from parallel someOtherAnimation()` means to play someOtherAnimation at the same
#       time as the current animation.


######################
# Constants

ROAR_SOUND = 0

# Normal enemies move at 6 pixels per animFrame, and can only move
# in orthoganal directions.
MOVEMENT_VECTORS = {
	"UP": (0, -6),
	"DOWN": (0, 6),
	"LEFT": (-6, 0),
	"RIGHT": (6, 0),
	"NONE": (0, 0)
}

FLOAT_ANIMATION = [
	-1, 0, 0, -1,
	-1, 0, 0, 0,
	1, 1, 0, 0,
	0, 1, 0, 1,
	0, 0, 0, -1
]

######################
# Main animation methods
#
# Their names here match the names of the functions in the Ghidra project


# For animationType Immobile and AnimationActionsOnly. The animation
# just cycles through the sprite animation of the current sprite group.
def animateInPlace():
	while True:
		stepAnimationLoop()
		yield nextAnimFrame()


# For animationType FloatingRaft. The animation makes an actor
# move up and down as if it's being moved by waves. The actor returns
# to the same y position every 20 frames.
def doRaftFloatAnimation():
	while True:
		# Loop through the whole animation on repeat
		for i in range(0, len(FLOAT_ANIMATION)):
			actor.position.y += FLOAT_ANIMATION[i]
			yield nextAnimFrame()


# For animationType PushableBlock, there is no animation or AI when it spawns.

# For animationType Boss, each boss has their own AI. See the scripts.py file in
# the boss fight's cell.

# For animationType Enemy:
def runEnemyAI():
	while True:
		yield from stepEnemyAI()

def stepEnemyAI():
	if isDemoZelda() and noEnemyActors():
		# Demo zelda has killed all the enemies on screen.
		endDemo()
		return

	
	if isInAggroDistance(slightlySmaller=False):
		moveVector, walkDuration = stepEnemyAI_rageMode()
	else:
		moveVector, walkDuration = stepEnemyAI_passiveMode()

	# Enemy doesn't walk yet; if it decides to throw a projectile, that
	# happens first.
	#yield from animateEnemyMovement(moveVector, walkDuration)
	
	if canFireAProjectile() and not isBoss() and randomDecision():
		createEnemyProjectile()

		# End the current frame. playAnimationForDuration takes control on the next frame.
		yield nextAnimFrame()
		yield from playAnimationForDuration(10)
	
	# End the current frame. animateEnemyMovement takes control on the next frame.
	yield nextAnimFrame()
	yield from animateEnemyMovement(moveVector, walkDuration)


def stepEnemyAI_passiveMode():
	actor.rageState = "Passive"

	walkDuration = randomPick([
		0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60
	])
	
	direction = randomPick(["UP", "DOWN", "LEFT", "RIGHT"])
	
	return MOVEMENT_VECTORS[direction], walkDuration


def stepEnemyAI_rageMode():
	# When changing from Passive to Rage, play a roar sound effect.
	if actor.rageState == "Passive":
		# TODO: How does the game prevent bosses from roaring?
		playSound(ROAR_SOUND)

	actor.rageState = "Rage"
	
	walkDuration = randomPick([0, 4, 8, 12])
	
	# The "NONE" option is used when the player is aligned with the actor (same x value or same y value).
	if randomDecision():
		vector = pickClosestToPlayer(["UP", "DOWN", "NONE"])
	else:
		vector = pickClosestToPlayer(["LEFT", "RIGHT", "NONE"])
	
	return vector, walkDuration


# For animationType MovingRaft:
def moveActorOnPath():
	# Loop through the whole animation once.
	for i in range(0, len(actor.path)):
		# Note: Numbers are encoded as signed shorts.
		actor.position.x += actor.path[i].x
		actor.position.y += actor.path[i].y
		yield nextAnimFrame()


# For animationType DiagonalBouncingSprite
def onAnimateDiagonallyBouncingActor():
	pass

# For animationType OrthoganalBouncingSprite
def onAnimateOrthoganallyBouncingActor():
	pass



######################
# High-Level Helpers
#
# All of these helpers do exactly what their name suggests. They're here to remove
# any ambiguity.

# This function advances the sprite's animation.
#
# The starting value of `currentFrame` is able to be customized, but it's always 0
# for every actor in the game.
def stepAnimationLoop():
	actor.animationCounter += 1
	if actor.animationCounter == actor.animationCounter:
		actor.currentFrame += 1
		if actor.currentFrame == actor.frameCount:
			actor.currentFrame = 0


def canFireAProjectile():
	if actor.hasCreatedProjectile:
		return False
	
	# Note: canFireProjectiles is a REALLY weird field. See
	# `curiosities/Actor Desc Projectile Field.md` for more info.
	if actor.canFireProjectiles == 0:
		return False

	if isDemoZelda() or isBoss():
		return False
	
	return True


# Picks the direction that gets the actor closer to the player. Actual game code is far more
# efficient than a distance formula, but this version is easier to understand.
def pickClosestToPlayer(options):
	bestVector = None
	bestDistance = 0
	for option in options:
		vector = MOVEMENT_VECTORS[option]
		distance = dist(actor.position + vector, player.position)
		if distance > bestDistance:
			bestVector = vector
			bestDistance = distance
	return bestVector


# The aggro distance check happens in two places, and they use the same numbers. But one place uses "<" while
# the other place uses "<=", so the aggro range is slightly different. The main check uses "<=".
def isInAggroDistance(slightlySmaller):
	deltaX = abs(actor.position.x - player.position.x)
	deltaY = abs(actor.position.y - player.position.y)

	if slightlySmaller:
		return deltaX < 120 and deltaY < 80
	else:
		return deltaX <= 120 and deltaY <= 80

	
def isDemoZelda():
	# If the player has an AI attached, then it must be demo-mode zelda.
	return actor.spriteType == "PlayerSprite"


def isBoss():
	return actor.metaType_maybe == "Boss"

def randomDecision() -> bool:
	return random(0, 1) == 0


# Used by boss AI to move to specific coordinates.
def moveToGoal(goalX, goalY):
	while actor.position != (goalX, goalY):
		# Move 8 pixels per frame, or less if the goal is close.
		actor.position.x += clamp(goalX - actor.position.x, min=-8, max=8)
		actor.position.y += clamp(goalY - actor.position.y, min=-8, max=8)
		stepAnimationLoop()
		yield nextAnimFrame()


# Used by boss AI to add randomness to the fight. The "duration" is actually the number
# of times that stepBossAsIfNormalEnemy() 
def runEnemyAIForSteps(steps):
	for i in range(0, steps):
		yield from stepEnemyAI()


def runAnimationForDuration(frames):
	for i in range(0, frames):
		stepAnimationLoop()
		yield nextAnimFrame()


def clamp(value, min, max):
	if value > max:
		return max
	if value < min:
		return min
	return value


def randomPick(options):
	return options[random(0, len(options))]

######################
# Low-Level Helpers
#
# This is mostly stuff that makes IDE's happy / complain less.

from math import sqrt, floor
from dataclasses import dataclass
from random import random as pythonRandom
from typing import Literal

def nextAnimFrame():
	pass


def random(low, high):
	return floor(pythonRandom() * (high - low) + low)


def dist(p1: "Coord", p2: "Coord"):
	dx = abs(p1.x - p2.x)
	dy = abs(p1.y - p2.y)
	return sqrt(dx*dx + dy*dy)


def playSound(index):
	pass

def createEnemyProjectile():
	pass

def endDemo():
	pass

def noEnemyActors():
	pass

def AllFunctionsEndTheFrame():
	pass

def setIsInvulnerable():
	pass

def useAttack():
	pass

def setAnimationGroup():
	pass

def wasteOneFrame():
	pass

@dataclass
class Coord:
	x: float = 0
	y: float = 0

@dataclass
class Actor:
	position: Coord
	spriteType: str
	metaType_maybe: str
	animationCounter: int
	currentFrame: int
	frameCount: int
	rageState: Literal["Passive", "Rage"]
	hasCreatedProjectile: bool
	canFireProjectiles: int
	path: list[Coord]

actor = Actor(Coord())
player = Actor(Coord())