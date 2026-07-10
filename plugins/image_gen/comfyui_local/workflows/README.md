# ComfyUI workflow routing

`comfyui_local` builds workflows dynamically via `generate.py` (Pony 832×1216 + detailers, Juggernaut 1024×1024).

Prompt routing examples:
- `portrait alice` → `--character alice --registry-mode portrait -m pony`
- `scene: bedroom, alice` → `--character alice --scene bedroom --registry-mode scene -m pony`
- `landscape manor dawn` → `-m juggernaut` (no character registry)