# AR4 Gripper Control in IsaacSim

Load the AR4 MK3 USD model in Isaac Sim with Python, and drive its parallel gripper through a smooth sinusoidal open-close motion using `ParallelGripper`.

<p align="center">
<video controls width="700">
  <source src="/videos/gripper_control.mp4" type="video/mp4">
</video>
</p>

---

## 0. What this tutorial covers

By the end of this walkthrough you will be able to:

1. Load the AR4 MK3 USD into an Isaac Sim from a Python script;
2. **Auto locate** the end-effector (`gripper_base_link`) instead of hard coding a long prim path;
3. Drive the gripper with `ParallelGripper` and a USD `mimic` joint so both jaws move together;
4. Animate the jaws with a sine wave so you can visually verify the control loop is working.

---

## 1. Prerequisites

- Isaac Sim **5.1**
- Python 3.10 (the interpreter shipped with Isaac Sim)
- An AR4 MK3 USD file. In this tutorial the path is:

```
F:/isaac/ar4_urdf/ar4_mk3_isaac/ar4_mk3_isaac.usd
```

If you only have a URDF, convert it with Isaac Sim's built-in **URDF Importer**. Tick `Fix Base Link` during import — otherwise the arm will spawn lying flat on the ground.

---

## 2. The big picture

Controlling the gripper boils down to two problems:

- **Find the end-effector prim.** `ParallelGripper` needs an `end_effector_prim_path`, and that path has to actually exist on the USD stage. URDF-imported paths tend to be deeply nested and version-dependent, so hard-coding them is brittle. We'll discover the prim at runtime instead.
- **Drive the gripper joint.** AR4's gripper has two parts — one active joint (`gripper_jaw1_joint`) plus a mimic joint where jaw2 follows jaw1. Setting `use_mimic_joints=True` on `ParallelGripper` is enough to handle the coupling.

Once those are sorted, the loop just needs to feed jaw1 a target position oscillating between `0` and `0.014` m.

---

## 3. Walking through the code

### 3.1 Boot SimulationApp

```python
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": False})
```

**This line must come before any other `isaacsim.*` import.** Isaac Sim is built on Kit, and most modules can only be loaded *after* `SimulationApp` is up. Get the order wrong and you'll see cryptic import errors.

`headless=False` opens the GUI — keep it on while debugging, flip it to `True` for training runs.

### 3.2 Imports and CLI args

```python
import argparse
import numpy as np
from isaacsim.core.api import World
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.core.utils.types import ArticulationAction
from isaacsim.robot.manipulators import SingleManipulator
from isaacsim.robot.manipulators.grippers import ParallelGripper
import omni.usd

parser = argparse.ArgumentParser()
parser.add_argument("--test", default=False, action="store_true")
args, _ = parser.parse_known_args()

USD_PATH   = r"F:/isaac/ar4_urdf/ar4_mk3_isaac/ar4_mk3_isaac.usd"
ROBOT_PRIM = "/World/ar4_mk3_isaac"
```

The `--test` flag is for CI: it lets the script auto-exit after a few seconds instead of running forever.

### 3.3 Create the World and load the USD

```python
my_world = World(stage_units_in_meters=1.0)
add_reference_to_stage(usd_path=USD_PATH, prim_path=ROBOT_PRIM)

# Force one stage update so the prims actually materialize
simulation_app.update()
```

⚠️ **`simulation_app.update()` is critical.** `add_reference_to_stage` only attaches a reference; the prim tree underneath is expanded on the next stage tick. If you immediately call `Traverse()` you'll get an empty result and waste an hour debugging — it's a timing issue, not a path issue.

### 3.4 Auto-discover the end-effector prim

```python
stage = omni.usd.get_context().get_stage()

def find_prim_suffix(suffix: str):
    hits = []
    for prim in stage.Traverse():
        p = prim.GetPath().pathString
        if p.endswith(suffix):
            hits.append(p)
    return hits

hits = find_prim_suffix("/gripper_base_link")
print("=== Found gripper_base_link prims ===")
for h in hits:
    print(h)

if len(hits) == 0:
    raise RuntimeError("can't find gripper_base_link, USD load failed")

# When several candidates exist, prefer the one under link_6
EE_PRIM = None
for h in hits:
    if "/link_6/" in h:
        EE_PRIM = h
        break
if EE_PRIM is None:
    EE_PRIM = hits[0]

print(f"=== Using EE_PRIM: {EE_PRIM} ===")
```

Why bother? Because URDF-imported USDs produce paths like:

```
/World/ar4_mk3_isaac/base_link/link_1/link_2/.../link_6/gripper_base_link
```

The exact hierarchy varies between importer versions. **Suffix matching is portable; hard-coded paths are not.**

The `link_6` preference handles a sneaky edge case: some USD models contain duplicate `gripper_base_link` prims (collision proxies, visual children, etc.) — the one nested under `link_6` is the actual kinematic end-effector.

### 3.5 Configure the ParallelGripper

```python
gripper = ParallelGripper(
    end_effector_prim_path=EE_PRIM,
    joint_prim_names=["gripper_jaw1_joint"],
    joint_opened_positions=np.array([0.014], dtype=np.float32),
    joint_closed_positions=np.array([0.0], dtype=np.float32),
    action_deltas=np.array([0.014], dtype=np.float32),
    use_mimic_joints=True,
)
```

Argument by argument:

| Argument | Meaning |
|---|---|
| `end_effector_prim_path` | The prim where forward kinematics terminates |
| `joint_prim_names` | The **active** joint name only |
| `joint_opened_positions` | Jaw1 position when fully open (meters); 14 mm for AR4 |
| `joint_closed_positions` | Jaw1 position when fully closed |
| `action_deltas` | Step size for discrete `open()` / `close()` actions |
| `use_mimic_joints=True` | **Key flag**: jaw2's mimic joint is driven automatically by USD's mimic API |

If you leave `use_mimic_joints=False`, you have to command jaw1 and jaw2 yourself, mirror the sign correctly, and stay in lockstep frame by frame. Even a 0.001 m mismatch can jam the jaws. Just set it to `True`.

### 3.6 Wrap it in a SingleManipulator

```python
robot = my_world.scene.add(
    SingleManipulator(
        prim_path=ROBOT_PRIM,
        name="ar4_mk3",
        end_effector_prim_path=EE_PRIM,
        gripper=gripper,
    )
)

my_world.scene.add_default_ground_plane()
my_world.reset()
my_world.play()
```

`SingleManipulator` is Isaac Sim's high-level wrapper that bundles "arm body + end-effector + gripper" into one object. From here on you can just call `robot.gripper.apply_action(...)`.

`my_world.reset()` **must** be called before `play()` — that's when joint handles, controllers, and other internal state get initialized. Skip it and you'll get an `articulation not initialized` error.

### 3.7 The sinusoidal control loop

```python
OPEN  = 0.014
CLOSE = 0.0
period_sec = 1.0   # smaller = faster
fps_est    = 60.0  # estimated sim frame rate

t = 0
while simulation_app.is_running():
    my_world.step(render=True)

    # Auto-resume if the user clicks Stop in the GUI
    if my_world.is_stopped():
        my_world.play()

    t += 1
    phase = (t / (fps_est * period_sec)) * 2.0 * np.pi
    s01 = 0.5 * (1.0 + np.sin(phase))      # remap to [0, 1]
    target = CLOSE + s01 * (OPEN - CLOSE)  # remap to jaw position

    robot.gripper.apply_action(
        ArticulationAction(joint_positions=[target])
    )

    if args.test and t > 180:
        break

simulation_app.close()
```

Why a sine wave instead of toggling `open()` / `close()`?

- **Square-wave switching** makes the gripper slam to the target at max velocity. It looks robotic, excites mechanical chatter, and makes it hard to tune stiffness/damping.
- **A sinusoidal target** gives the PD controller a smooth trajectory it can actually track. The motion looks like breathing, and it's a much better signal for tuning gains.

`s01 = 0.5 * (1 + sin(x))` is the standard trick to remap `sin` from `[-1, 1]` into `[0, 1]`.

---

## 4. Running it

Save the script as `ar4_gripper_demo.py` and run it with Isaac Sim's bundled Python:

**Windows:**
```bash
"C:\Users\<you>\AppData\Local\ov\pkg\isaac-sim-5.1.0\python.bat" ar4_gripper_demo.py
```

**Linux:**
```bash
./python.sh ar4_gripper_demo.py
```

If everything is wired up correctly, the GUI opens, AR4 stands on the ground plane, and the gripper opens and closes once per second.

---

## 5. Common pitfalls

**1. `gripper_base_link` not found**
Double-check the USD path. On Windows, use a raw string `r"..."` or escape the backslashes.

**2. `articulation is not initialized`**
99% of the time you forgot `my_world.reset()`, or you skipped `simulation_app.update()` after `add_reference_to_stage`.

**3. Only one finger moves**
The mimic joint isn't active. Two possible causes:
- `use_mimic_joints=False` (the default — you have to opt in explicitly);
- The mimic tag wasn't carried over during URDF → USD conversion. Open the USD file and search for `physics:MimicAPI`. If it's missing, either patch it in by hand or re-import with a newer version of the URDF importer.

**4. Frame-rate jitter throws off the period**
`fps_est = 60.0` is just an estimate. For an exact period, drive the phase from sim time instead of frame count:

```python
phase = (my_world.current_time / period_sec) * 2.0 * np.pi
```

Now the cycle is exactly `period_sec` seconds regardless of actual frame rate.

---

## 6. Full script

> Drop-in runnable. Just update `USD_PATH`.

```python
from isaacsim import SimulationApp
simulation_app = SimulationApp({"headless": False})

import argparse
import numpy as np
from isaacsim.core.api import World
from isaacsim.core.utils.stage import add_reference_to_stage
from isaacsim.core.utils.types import ArticulationAction
from isaacsim.robot.manipulators import SingleManipulator
from isaacsim.robot.manipulators.grippers import ParallelGripper
import omni.usd

parser = argparse.ArgumentParser()
parser.add_argument("--test", default=False, action="store_true")
args, _ = parser.parse_known_args()

USD_PATH   = r"F:/isaac/ar4_urdf/ar4_mk3_isaac/ar4_mk3_isaac.usd"
ROBOT_PRIM = "/World/ar4_mk3_isaac"

my_world = World(stage_units_in_meters=1.0)
add_reference_to_stage(usd_path=USD_PATH, prim_path=ROBOT_PRIM)
simulation_app.update()

stage = omni.usd.get_context().get_stage()

def find_prim_suffix(suffix: str):
    return [p.GetPath().pathString for p in stage.Traverse()
            if p.GetPath().pathString.endswith(suffix)]

hits = find_prim_suffix("/gripper_base_link")
print("=== Found gripper_base_link prims ===")
for h in hits:
    print(h)
if not hits:
    raise RuntimeError("can't find gripper_base_link, USD load failed")

EE_PRIM = next((h for h in hits if "/link_6/" in h), hits[0])
print(f"=== Using EE_PRIM: {EE_PRIM} ===")

gripper = ParallelGripper(
    end_effector_prim_path=EE_PRIM,
    joint_prim_names=["gripper_jaw1_joint"],
    joint_opened_positions=np.array([0.014], dtype=np.float32),
    joint_closed_positions=np.array([0.0], dtype=np.float32),
    action_deltas=np.array([0.014], dtype=np.float32),
    use_mimic_joints=True,
)

robot = my_world.scene.add(
    SingleManipulator(
        prim_path=ROBOT_PRIM,
        name="ar4_mk3",
        end_effector_prim_path=EE_PRIM,
        gripper=gripper,
    )
)

my_world.scene.add_default_ground_plane()
my_world.reset()
my_world.play()

OPEN, CLOSE = 0.014, 0.0
period_sec, fps_est = 1.0, 60.0

t = 0
while simulation_app.is_running():
    my_world.step(render=True)
    if my_world.is_stopped():
        my_world.play()

    t += 1
    phase = (t / (fps_est * period_sec)) * 2.0 * np.pi
    s01 = 0.5 * (1.0 + np.sin(phase))
    target = CLOSE + s01 * (OPEN - CLOSE)

    robot.gripper.apply_action(
        ArticulationAction(joint_positions=[target])
    )

    if args.test and t > 180:
        break

simulation_app.close()
```



