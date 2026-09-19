import bpy
import subprocess
import os
import glob
import atexit


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


def convert_scene(scene, force=False):
    """Convert the rendered image sequence of *scene* to an .mp4.

    Returns the mp4 path on success, None if skipped or failed.
    With force=True the frame-range check is bypassed and the sequence is
    taken from whatever frames exist on disk; this is what render queue
    tools (which often render frame by frame) should call once an item
    has finished.
    """
    prefs = get_addon_prefs()

    if not prefs.enabled and not force:
        return None

    render = scene.render

    # Skip single still-frame renders, only handle sequences/animations.
    if not force and scene.frame_start == scene.frame_end:
        return None

    # Skip if Blender is already outputting a video container directly.
    if render.image_settings.file_format in {"FFMPEG", "AVI_JPEG", "AVI_RAW"}:
        return None

    job = _job_from_scene(scene)
    return _convert_job(job, prefs_snapshot(prefs))


def _job_from_scene(scene):
    """Capture everything the conversion needs as plain values.

    Resolving the real on-disk path via frame_path() expands Blender 5 output
    template variables such as {scene_name}, {camera_name} or {blend_name}
    (which Blender Render Queue relies on) and applies padding, extension and
    relative-path rules. Reading render.filepath literally would leave the
    template text unexpanded and point at a folder that does not exist.
    """
    render = scene.render
    return {
        "first_path": render.frame_path(frame=scene.frame_start),
        "fps": render.fps / render.fps_base,
        "frame_start": scene.frame_start,
        "blend_name": os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else "render",
    }


def prefs_snapshot(prefs):
    return {"ffmpeg_path": prefs.ffmpeg_path, "notify": prefs.notify}


def _convert_job(job, prefs):
    """Pure filesystem + ffmpeg conversion. Safe to call at interpreter exit,
    when bpy data may already be gone."""
    first_path = job["first_path"]
    fps = job["fps"]
    blend_name = job["blend_name"]

    output_dir = os.path.dirname(first_path)
    if not output_dir or not os.path.isdir(output_dir):
        print(f"[Render to MP4] Output directory does not exist: {output_dir!r}, skipping conversion.")
        return None

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
        return None

    pattern_glob = os.path.join(output_dir, f"{glob.escape(basename)}*.{ext}")
    frames = sorted(glob.glob(pattern_glob))

    if len(frames) < 2:
        print(f"[Render to MP4] Fewer than 2 frames found matching {pattern_glob}, skipping.")
        return None

    # Start from the lowest-numbered frame actually on disk rather than
    # scene.frame_start: render queue tools may have changed the scene range
    # per frame, and this keeps the video complete either way.
    def _frame_number(path):
        stem_ = os.path.splitext(os.path.basename(path))[0]
        digits = stem_[len(basename):]
        return int(digits) if digits.isdigit() else None

    numbers = [n for n in (_frame_number(f) for f in frames) if n is not None]
    start_number = min(numbers) if numbers else job["frame_start"]

    ffmpeg_pattern = os.path.join(output_dir, f"{basename}%0{padding}d.{ext}")

    # Name the video after the file prefix; if the prefix is empty (frames are
    # just numbers, as with a template folder path) fall back to the folder
    # name, which is usually the expanded {scene_name}/{camera_name}.
    folder_name = os.path.basename(output_dir.rstrip(os.sep))
    mp4_name = f"{basename.rstrip('_-.') or folder_name or blend_name}.mp4"
    mp4_path = os.path.join(output_dir, mp4_name)

    ffmpeg_bin = find_ffmpeg(prefs["ffmpeg_path"])

    cmd = [
        ffmpeg_bin, "-y",
        "-framerate", str(fps),
        "-start_number", str(start_number),
        "-pattern_type", "sequence",
        "-i", ffmpeg_pattern,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        mp4_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"[Render to MP4] Created {mp4_path} ({len(frames)} frames @ {fps:g} fps)")
        _converted_dirs.add(output_dir)
        if prefs["notify"]:
            subprocess.run([
                "osascript", "-e",
                f'display notification "{mp4_name} created" with title "Render to MP4 v1.2.0"',
            ])
        return mp4_path
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="ignore") if e.stderr else str(e)
        print(f"[Render to MP4] ffmpeg failed: {stderr}")
        if prefs["notify"]:
            subprocess.run([
                "osascript", "-e",
                'display notification "ffmpeg conversion failed, check Blender console" with title "Render to MP4"',
            ])
        return None


# --- Session state ---------------------------------------------------------
# Folders already converted in this Blender session (avoid doing it twice),
# and jobs seen via render_write that still need converting at exit.
_converted_dirs = set()
_pending_jobs = {}


def render_complete_handler(scene):
    """Blender's render_complete hook: fires after a normal animation render
    started from the UI or from a plain `blender -b file -a`."""
    convert_scene(scene, force=False)


def render_write_handler(scene):
    """Fires every time Blender writes a frame to disk.

    Render queue tools such as Blender Render Queue drive Blender frame by
    frame from their own script, so render_complete never sees a whole
    sequence. Here we just remember where frames are going; the conversion
    happens once, when the background Blender process exits.
    """
    if not bpy.app.background:
        return
    try:
        prefs = get_addon_prefs()
        if not prefs.enabled:
            return
        if scene.render.image_settings.file_format in {"FFMPEG", "AVI_JPEG", "AVI_RAW"}:
            return
        job = _job_from_scene(scene)
        key = os.path.dirname(job["first_path"])
        _pending_jobs[key] = (job, prefs_snapshot(prefs))
    except Exception as e:  # never let a hook break the render
        print(f"[Render to MP4] render_write hook error: {e}")


def _convert_pending_at_exit():
    """atexit hook: convert every sequence written during this background
    session that has not been converted yet. Uses only cached plain values,
    so it does not depend on bpy data still being alive."""
    for key, (job, prefs) in list(_pending_jobs.items()):
        if key in _converted_dirs:
            continue
        try:
            _convert_job(job, prefs)
        except Exception as e:
            print(f"[Render to MP4] exit conversion failed for {key}: {e}")
    _pending_jobs.clear()


class RENDER_OT_to_mp4_now(bpy.types.Operator):
    """Convert this scene's rendered image sequence to MP4 now.

    Meant for render queue tools that render frame by frame (e.g. Blender
    Render Queue): put ``bpy.ops.render.to_mp4_now()`` in the tool's
    post-render Python expression and the video is created once per item,
    from whatever frames are on disk, regardless of how the frames were
    rendered.
    """
    bl_idname = "render.to_mp4_now"
    bl_label = "Render to MP4 now"
    bl_options = {"REGISTER"}

    def execute(self, context):
        result = convert_scene(context.scene, force=True)
        if result:
            self.report({"INFO"}, f"Created {result}")
            return {"FINISHED"}
        self.report({"WARNING"}, "Render to MP4: nothing converted, see console")
        return {"CANCELLED"}


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


classes = (RenderToMP4Preferences, RENDER_OT_to_mp4_now)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.app.handlers.render_complete.append(render_complete_handler)
    bpy.app.handlers.render_write.append(render_write_handler)
    atexit.register(_convert_pending_at_exit)


def unregister():
    if render_complete_handler in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.remove(render_complete_handler)
    if render_write_handler in bpy.app.handlers.render_write:
        bpy.app.handlers.render_write.remove(render_write_handler)
    try:
        atexit.unregister(_convert_pending_at_exit)
    except Exception:
        pass
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
