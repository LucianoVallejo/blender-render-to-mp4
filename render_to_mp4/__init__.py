import bpy
import subprocess
import os
import glob
import atexit
import tempfile
import sys

from bpy.app.handlers import persistent


ADDON_VERSION = "1.3.0"
MOVIE_FORMATS = {"FFMPEG", "AVI_JPEG", "AVI_RAW"}
PLAYBLAST_SUFFIX = "_playblast"


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
    if render.image_settings.file_format in MOVIE_FORMATS:
        return None

    job = _job_from_scene(scene)
    return _convert_job(job, prefs_snapshot(prefs))


def _job_from_scene(scene, frame_start=None, frame_end=None, frame_step=None):
    """Capture everything the conversion needs as plain values.

    Resolving the real on-disk path via frame_path() expands Blender 5 output
    template variables such as {scene_name}, {camera_name} or {blend_name}
    (which Blender Render Queue relies on) and applies padding, extension and
    relative-path rules. Reading render.filepath literally would leave the
    template text unexpanded and point at a folder that does not exist.
    """
    render = scene.render
    frame_start = scene.frame_start if frame_start is None else frame_start
    frame_end = scene.frame_end if frame_end is None else frame_end
    frame_step = scene.frame_step if frame_step is None else frame_step
    return {
        "first_path": render.frame_path(frame=frame_start),
        "fps": render.fps / render.fps_base,
        "frame_start": frame_start,
        "frame_end": frame_end,
        "frame_step": frame_step,
        "blend_name": os.path.splitext(os.path.basename(bpy.data.filepath))[0] if bpy.data.filepath else "render",
    }


def _scene_playback_range(scene):
    """Return the range used by Viewport Render Animation."""
    if scene.use_preview_range:
        return scene.frame_preview_start, scene.frame_preview_end
    return scene.frame_start, scene.frame_end


def _playblast_filepath(filepath):
    """Derive a temporary output path without modifying the saved path.

    Directory paths become sibling directories ending in ``_playblast``;
    filename-prefix paths receive ``_playblast_`` before their frame number.
    """
    filepath = filepath or "//render/"
    if filepath.endswith(("/", "\\")):
        separator = filepath[-1]
        stripped = filepath.rstrip("/\\")
        return f"{stripped}{PLAYBLAST_SUFFIX}{separator}" if stripped else f"//{PLAYBLAST_SUFFIX.lstrip('_')}/"

    stripped = filepath.rstrip("_-. ")
    return f"{stripped or filepath}{PLAYBLAST_SUFFIX}_"


def _expected_frame_paths(scene, frame_start, frame_end, frame_step):
    return [
        scene.render.frame_path(frame=frame)
        for frame in range(frame_start, frame_end + 1, max(1, frame_step))
    ]


def _file_signature(path):
    try:
        stat = os.stat(path)
        return stat.st_mtime_ns, stat.st_size
    except OSError:
        return None


def prefs_snapshot(prefs):
    return {"ffmpeg_path": prefs.ffmpeg_path, "notify": prefs.notify}


def _show_notification(message, title):
    """Best-effort macOS notification that never changes conversion status."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        print(f"[Render to MP4] Notification failed: {exc}")


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
    explicit_frames = job.get("frames")
    frames = list(explicit_frames) if explicit_frames else sorted(glob.glob(pattern_glob))

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

    # Name the video after the file prefix; if the prefix is empty (frames are
    # just numbers, as with a template folder path) fall back to the folder
    # name, which is usually the expanded {scene_name}/{camera_name}.
    folder_name = os.path.basename(output_dir.rstrip(os.sep))
    mp4_name = f"{basename.rstrip('_-.') or folder_name or blend_name}.mp4"
    mp4_path = os.path.join(output_dir, mp4_name)

    ffmpeg_bin = find_ffmpeg(prefs["ffmpeg_path"])
    concat_path = None

    if explicit_frames:
        # A concat manifest encodes exactly this playblast's frames. This
        # avoids stale files and also supports frame steps greater than one.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ffconcat",
            prefix=".render_to_mp4_",
            dir=output_dir,
            encoding="utf-8",
            delete=False,
        ) as manifest:
            concat_path = manifest.name
            duration = 1.0 / fps
            for frame_path in frames:
                safe_path = frame_path.replace("\\", "/").replace("'", r"'\''")
                manifest.write(f"file '{safe_path}'\n")
                manifest.write(f"duration {duration:.12f}\n")
            safe_last = frames[-1].replace("\\", "/").replace("'", r"'\''")
            manifest.write(f"file '{safe_last}'\n")

        cmd = [
            ffmpeg_bin, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_path,
            "-r", str(fps),
            "-frames:v", str(len(frames)),
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            mp4_path,
        ]
    else:
        ffmpeg_pattern = os.path.join(output_dir, f"{basename}%0{padding}d.{ext}")
        cmd = [
            ffmpeg_bin, "-y",
            "-framerate", str(fps),
            "-start_number", str(start_number),
            "-pattern_type", "sequence",
            "-i", ffmpeg_pattern,
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            mp4_path,
        ]

    try:
        subprocess.run(cmd, check=True, capture_output=True)
        print(f"[Render to MP4] Created {mp4_path} ({len(frames)} frames @ {fps:g} fps)")
        _converted_dirs.add(output_dir)
        if prefs["notify"]:
            _show_notification(f"{mp4_name} created", f"Render to MP4 v{ADDON_VERSION}")
        return mp4_path
    except (subprocess.CalledProcessError, OSError) as e:
        stderr_value = getattr(e, "stderr", None)
        stderr = stderr_value.decode(errors="ignore") if stderr_value else str(e)
        print(f"[Render to MP4] ffmpeg failed: {stderr}")
        if prefs["notify"]:
            _show_notification("ffmpeg conversion failed, check Blender console", "Render to MP4")
        return None
    finally:
        if concat_path:
            try:
                os.remove(concat_path)
            except OSError:
                pass


# --- Session state ---------------------------------------------------------
# Folders already converted in this Blender session (avoid doing it twice),
# and jobs seen via render_write that still need converting at exit.
_converted_dirs = set()
_pending_jobs = {}
_active_playblast_operator = None


@persistent
def render_complete_handler(scene):
    """Blender's render_complete hook: fires after an animation render.

    Both handlers are @persistent: without it Blender drops them whenever a
    .blend file is loaded, which is exactly what happens in a background
    render (`blender -b file.blend ...`) where the add-on registers before
    the file is opened. That was why queue renders never produced a video.
    """
    convert_scene(scene, force=False)


@persistent
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
        if scene.render.image_settings.file_format in MOVIE_FORMATS:
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


class RENDER_OT_playblast_to_mp4(bpy.types.Operator):
    """Render the active viewport to a temporary _playblast path and create an MP4."""

    bl_idname = "render.playblast_to_mp4"
    bl_label = "Viewport Playblast to MP4"
    bl_description = (
        "Render the active viewport to a temporary _playblast output, create an MP4, "
        "then restore the original output path"
    )
    bl_options = {"REGISTER"}

    _timer = None
    _scene = None
    _window_manager = None
    _original_filepath = None
    _original_use_overwrite = None
    _temporary_filepath = None
    _job = None
    _prefs = None
    _expected_frames = None
    _before_signatures = None
    _job_seen = False
    _cancel_requested = False
    _cleanup_scheduled = False

    @classmethod
    def poll(cls, context):
        return not bpy.app.background and context.area is not None and context.area.type == "VIEW_3D"

    def _remove_timer(self):
        if self._timer is not None and self._window_manager is not None:
            try:
                self._window_manager.event_timer_remove(self._timer)
            except ReferenceError:
                pass
            self._timer = None

    def _restore_render_settings(self):
        if self._scene is not None:
            try:
                self._scene.render.filepath = self._original_filepath
                self._scene.render.use_overwrite = self._original_use_overwrite
            except ReferenceError:
                pass

    def _clear_active_operator(self):
        global _active_playblast_operator
        if _active_playblast_operator is self:
            _active_playblast_operator = None

    def _cleanup_now(self):
        self._remove_timer()
        self._restore_render_settings()
        self._clear_active_operator()

    def _cleanup_when_render_stops(self):
        """Never restore the final-render path while OpenGL is still writing."""
        self._remove_timer()
        if not bpy.app.is_job_running("RENDER"):
            self._cleanup_now()
            return
        if self._cleanup_scheduled:
            return

        self._cleanup_scheduled = True

        def deferred_cleanup():
            if bpy.app.is_job_running("RENDER"):
                return 0.25
            self._cleanup_scheduled = False
            self._cleanup_now()
            return None

        bpy.app.timers.register(deferred_cleanup, first_interval=0.25)

    def _finish(self, context):
        self._cleanup_now()

        if self._cancel_requested:
            self.report({"INFO"}, "Playblast cancelled; output path restored")
            return {"CANCELLED"}

        changed_frames = [
            path for path in self._expected_frames
            if _file_signature(path) is not None
            and _file_signature(path) != self._before_signatures.get(path)
        ]

        if len(changed_frames) != len(self._expected_frames):
            self.report(
                {"WARNING"},
                f"Playblast incomplete ({len(changed_frames)}/{len(self._expected_frames)} frames); no MP4 created",
            )
            return {"CANCELLED"}

        self._job["frames"] = changed_frames
        result = _convert_job(self._job, self._prefs)
        if result:
            self.report({"INFO"}, f"Created {result}; output path restored")
            return {"FINISHED"}

        self.report({"WARNING"}, "Playblast finished but MP4 conversion failed; output path restored")
        return {"CANCELLED"}

    def invoke(self, context, event):
        global _active_playblast_operator

        if _active_playblast_operator is not None:
            self.report({"WARNING"}, "A playblast is already being finalized")
            return {"CANCELLED"}
        if bpy.app.is_job_running("RENDER"):
            self.report({"WARNING"}, "Another render is already running")
            return {"CANCELLED"}

        scene = context.scene
        render = scene.render
        if render.image_settings.file_format in MOVIE_FORMATS:
            self.report(
                {"WARNING"},
                "Playblast to MP4 requires an image-sequence output format such as PNG or JPEG",
            )
            return {"CANCELLED"}

        frame_start, frame_end = _scene_playback_range(scene)
        frame_step = max(1, scene.frame_step)

        self._scene = scene
        self._window_manager = context.window_manager
        self._original_filepath = render.filepath
        self._original_use_overwrite = render.use_overwrite
        self._temporary_filepath = _playblast_filepath(render.filepath)
        self._prefs = prefs_snapshot(get_addon_prefs())
        self._cancel_requested = False
        self._job_seen = False
        self._cleanup_scheduled = False
        _active_playblast_operator = self

        try:
            render.filepath = self._temporary_filepath
            render.use_overwrite = True
            self._job = _job_from_scene(scene, frame_start, frame_end, frame_step)
            self._expected_frames = _expected_frame_paths(scene, frame_start, frame_end, frame_step)
            self._before_signatures = {path: _file_signature(path) for path in self._expected_frames}

            output_dir = os.path.dirname(self._job["first_path"])
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            result = bpy.ops.render.opengl("INVOKE_DEFAULT", animation=True, view_context=True)
            if "RUNNING_MODAL" not in result:
                raise RuntimeError("Blender did not start the viewport render job")

            # The native animation operator creates its render job before it
            # returns RUNNING_MODAL, so the next timer tick may safely treat a
            # non-running job as completed (important for very short playblasts).
            self._job_seen = True
            self._timer = context.window_manager.event_timer_add(0.25, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}
        except Exception as exc:
            self._cancel_requested = True
            self._cleanup_when_render_stops()
            self.report({"ERROR"}, f"Could not start playblast: {exc}")
            return {"CANCELLED"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._cancel_requested = True
            return {"PASS_THROUGH"}

        if event.type != "TIMER" or event.timer != self._timer:
            return {"PASS_THROUGH"}

        if bpy.app.is_job_running("RENDER"):
            self._job_seen = True
            return {"PASS_THROUGH"}

        return self._finish(context)

    def cancel(self, context):
        self._cancel_requested = True
        self._cleanup_when_render_stops()


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


classes = (RenderToMP4Preferences, RENDER_OT_to_mp4_now, RENDER_OT_playblast_to_mp4)


def draw_playblast_menu(self, context):
    self.layout.separator()
    self.layout.operator(
        RENDER_OT_playblast_to_mp4.bl_idname,
        text="Viewport Render Animation to MP4",
    )


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_view.append(draw_playblast_menu)
    if render_complete_handler not in bpy.app.handlers.render_complete:
        bpy.app.handlers.render_complete.append(render_complete_handler)
    if render_write_handler not in bpy.app.handlers.render_write:
        bpy.app.handlers.render_write.append(render_write_handler)
    atexit.register(_convert_pending_at_exit)


def unregister():
    global _active_playblast_operator
    if _active_playblast_operator is not None:
        _active_playblast_operator._cancel_requested = True
        _active_playblast_operator._cleanup_when_render_stops()
    try:
        bpy.types.VIEW3D_MT_view.remove(draw_playblast_menu)
    except Exception:
        pass
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
