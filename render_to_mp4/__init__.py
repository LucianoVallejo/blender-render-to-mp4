import bpy
import subprocess
import os
import glob


def find_ffmpeg(prefs_path):
    """Return a usable ffmpeg binary path.

    GUI apps on macOS (including Blender and render-queue tools) do not
    inherit your shell's PATH, so a plain "ffmpeg" call often fails even
    though it works fine from Terminal. We check common install
    locations first, then fall back to whatever preference the user set.
    """
    if prefs_path and os.path.isfile(prefs_path):
        return prefs_path

    candidates = [
        "/opt/homebrew/bin/ffmpeg",  # Homebrew on Apple Silicon
        "/usr/local/bin/ffmpeg",     # Homebrew on Intel Macs
        "/usr/bin/ffmpeg",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    return "ffmpeg"  # last resort: hope it's on PATH


def get_addon_prefs():
    return bpy.context.preferences.addons[__package__].preferences


def render_complete_handler(scene):
    prefs = get_addon_prefs()

    if not prefs.enabled:
        return

    render = scene.render

    # Skip single still-frame renders, only handle sequences/animations.
    if scene.frame_start == scene.frame_end:
        return

    # Skip if Blender is already outputting a video container directly.
    if render.image_settings.file_format in {"FFMPEG", "AVI_JPEG", "AVI_RAW"}:
        return

    # Resolve the real on-disk path the same way Blender does when it writes
    # frames. This expands Blender 5 output template variables such as
    # {scene_name}, {camera_name} or {blend_name} (which Blender Render Queue
    # relies on) and applies the frame padding, extension and relative-path
    # rules for us. Reading render.filepath literally would leave the
    # template text unexpanded and point at a folder that does not exist.
    first_path = render.frame_path(frame=scene.frame_start)

    output_dir = os.path.dirname(first_path)
    if not output_dir or not os.path.isdir(output_dir):
        print(f"[Render to MP4] Output directory does not exist: {output_dir!r}, skipping conversion.")
        return

    first_name = os.path.basename(first_path)
    stem, ext = os.path.splitext(first_name)
    ext = ext.lstrip(".")

    # The trailing digits of the frame name are the frame number; their
    # length is the padding and whatever precedes them is the prefix.
    basename = ""
    for i in range(len(stem)):
        if stem[i:].isdigit():
            basename = stem[:i]
            padding = len(stem) - i
            break
    else:
        print(f"[Render to MP4] Could not detect frame numbering in {first_name!r}, skipping.")
        return

    pattern_glob = os.path.join(output_dir, f"{glob.escape(basename)}*.{ext}")
    frames = sorted(glob.glob(pattern_glob))

    if len(frames) < 2:
        print(f"[Render to MP4] Fewer than 2 frames found matching {pattern_glob}, skipping.")
        return

    ffmpeg_pattern = os.path.join(output_dir, f"{basename}%0{padding}d.{ext}")

    blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else "render"
    # Name the video after the file prefix; if the prefix is empty (frames are
    # just numbers, as with a template folder path) fall back to the folder
    # name, which is usually the expanded {scene_name}/{camera_name}.
    folder_name = os.path.basename(output_dir.rstrip(os.sep))
    mp4_name = f"{basename.rstrip('_-.') or folder_name or blend_name}.mp4"
    mp4_path = os.path.join(output_dir, mp4_name)

    fps = render.fps / render.fps_base
    ffmpeg_bin = find_ffmpeg(prefs.ffmpeg_path)

    cmd = [
        ffmpeg_bin, "-y",
        "-framerate", str(fps),
        "-start_number", str(scene.frame_start),
        "-pattern_type", "sequence",
        "-i", ffmpeg_pattern,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        mp4_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"[Render to MP4] Created {mp4_path}")
        if prefs.notify:
            subprocess.run([
                "osascript", "-e",
                f'display notification "{mp4_name} created" with title "Render to MP4 v1.1.0"',
            ])
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="ignore") if e.stderr else str(e)
        print(f"[Render to MP4] ffmpeg failed: {stderr}")
        if prefs.notify:
            subprocess.run([
                "osascript", "-e",
                'display notification "ffmpeg conversion failed, check Blender console" with title "Render to MP4"',
            ])


class RenderToMP4Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    enabled: bpy.props.BoolProperty(
        name="Enabled",
        description="Automatically convert the rendered sequence to MP4 after each render",
        default=True,
    )
    ffmpeg_path: bpy.props.StringProperty(
        name="ffmpeg path",
        description="Full path to the ffmpeg binary. Leave empty to auto-detect common install locations (Homebrew, /usr/bin).",
        subtype="FILE_PATH",
        default="",
    )
    notify: bpy.props.BoolProperty(
        name="macOS notification",
        description="Show a macOS notification when the conversion finishes or fails",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "enabled")
        layout.prop(self, "ffmpeg_path")
        layout.prop(self, "notify")


classes = (RenderToMP4Preferences,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.render_complete.append(render_complete_handler)


def unregister():
    if render_complete_handler in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(render_complete_handler)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
