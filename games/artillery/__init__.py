"""artillery - tiny curses artillery sandbox.

Run (from games/):  python3 -m artillery     or     python3 artillery
Press ? in game for keys.

Modes: Sandbox (free fire at targets) and Duel (1v1 pass and play, turn based).
Wind (game settings, on by default) pushes shells; fire control ignores it.

Modules:
  config    constants             world     terrain generation, craters, lakes
  content   guns, shells, fuses   physics   projectile flight, firing tables
  entities  units, targets        keys      key bindings and the saved keymap
  game      state and rules       controls  keyboard handling (mixin)
  view      side view (mixin)     panels    maps, gauge, dial, tables, HUD (mixin)
  overlays  menus, help, dialogs  main      curses setup and main loop

Extending: add entries to FUSES, SHELLS and GUNS in content.py.
  - A fuse is a function(projectile) -> bool (True = detonate in the air).
    Ground contact always detonates.
  - A shell picks a fuse by key and sets blast radius, drag, default fuse time.
  - A gun lists its charges (muzzle velocities), which shells it can load,
    whether it is mobile, whether it has fire-control prediction, and limits.
"""
