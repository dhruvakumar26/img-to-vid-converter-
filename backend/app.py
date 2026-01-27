import os
import uuid
import subprocess
import traceback
from flask import Flask, request, jsonify, send_from_directory, send_file
from threading import Thread
from pathlib import Path

APP_DIR = Path(__file__).parent
CONV_DIR = APP_DIR / "conversions"
CONV_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
jobs = {}  # job_id -> {status, out_path, error}

def run_conversion(job_id, image_paths, audio_path):
    try:
        workdir = Path(CONV_DIR / job_id)
        workdir.mkdir(parents=True, exist_ok=True)

        # 1. Convert to uniform JPGs (Existing step)
        for idx, src in enumerate(image_paths, start=1):
            dst = workdir / f"img{idx:03d}.jpg"
            subprocess.run(["ffmpeg", "-y", "-i", str(src), str(dst)], check=True, capture_output=True)

        temp_video = workdir / "temp_video.mp4"

        # 2. Build video with SCALING and PADDING (The Fix)
        # This forces a 1920x1080 output and ensures dimensions are even
        vf_chain = (
            "scale=1920:1080:force_original_aspect_ratio=decrease,"
            "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        )

        print(f"[{job_id}] Starting FFmpeg video encode...")
        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", "1",
            "-i", str(workdir / "img%03d.jpg"),
            "-vf", vf_chain,
            "-c:v", "libx264",
            "-r", "30",
            "-pix_fmt", "yuv420p",
            str(temp_video)
        ], check=True, capture_output=True)

        # 3. Final Merge
        final_out = workdir / "output.mp4"
        if audio_path and os.path.exists(audio_path):
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(temp_video),
                "-i", str(audio_path),
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                str(final_out)
            ], check=True, capture_output=True)
        else:
            os.replace(str(temp_video), str(final_out))

        jobs[job_id]["status"] = "done"
        jobs[job_id]["out_path"] = str(final_out)
        print(f"[{job_id}] Job Complete: {final_out}")

    except subprocess.CalledProcessError as cpe:
        error_msg = cpe.stderr.decode() if cpe.stderr else str(cpe)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = error_msg
        print(f"[{job_id}] FFmpeg Error: {error_msg}")
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        print(f"[{job_id}] General Error: {e}")

def run_conversion1(job_id, image_paths, audio_path):
    try:
        workdir = CONV_DIR / job_id
        # image_paths and audio_path are strings (absolute/relative paths)
        # Convert to Path objects for convenience
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)

        # Log inputs
        print(f"[{job_id}] run_conversion starting. images={image_paths}, audio={audio_path}")

        # (Safety) ensure images exist and are non-empty
        for p in image_paths:
            if not os.path.exists(p) or os.path.getsize(p) == 0:
                raise RuntimeError(f"Input image missing or empty: {p}")

        # Convert all images to .jpg (uniform)
        converted_images = []
        for idx, src in enumerate(image_paths, start=1):
            dst = workdir / f"img{idx:03d}.jpg"
            # Use ffmpeg to convert to jpg (overwrites if exists)
            subprocess.run(["ffmpeg", "-y", "-i", str(src), str(dst)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            converted_images.append(str(dst))
            print(f"[{job_id}] converted {src} -> {dst} (size={os.path.getsize(dst)})")

        temp_video = workdir / "temp_video.mp4"
        # Build video from sequence (pattern img%03d.jpg)
        # framerate: 1 image per second (adjust as needed). Using -r 30 for output framerate.
        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", "1",
            "-i", str(workdir / "img%03d.jpg"),
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v", "libx264", 
            "-r", "30", 
            "-pix_fmt", "yuv420p",
            str(temp_video)
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) # Capturing output for debugging
        #subprocess.run([
        #    "ffmpeg", "-y",
        #    "-framerate", "1",
        #    "-i", str(workdir / "img%03d.jpg"),
        #    "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
        #    str(temp_video)
        #], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[{job_id}] temp video created: {temp_video} (size={os.path.getsize(temp_video)})")

        final_out = workdir / "output.mp4"
        if audio_path:
            # Ensure audio exists and not empty
            if not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                raise RuntimeError(f"Audio missing or empty: {audio_path}")

            # Merge video and audio; shortest to stop at shorter stream
            subprocess.run([
                "ffmpeg", "-y",
                "-i", str(temp_video),
                "-i", str(audio_path),
                "-c:v", "copy", "-c:a", "aac", "-shortest",
                str(final_out)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # No audio; rename temp to final
            os.replace(str(temp_video), str(final_out))

        jobs[job_id]["status"] = "done"
        jobs[job_id]["out_path"] = str(final_out)
        print(f"[{job_id}] conversion done -> {final_out} (size={os.path.getsize(final_out)})")

    except subprocess.CalledProcessError as cpe:
        tb = traceback.format_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"ffmpeg error: {cpe}; traceback: {tb}"
        print(f"[{job_id}] ffmpeg failed: {cpe}\n{tb}")
    except Exception as e:
        tb = traceback.format_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"error: {e}; traceback: {tb}"
        print(f"[{job_id}] conversion error: {e}\n{tb}")

@app.route("/api/convert", methods=["POST"])
def convert():
    # Get files from request
    image_files = request.files.getlist("images")
    audio_file = request.files.get("audio")

    if not image_files:
        return jsonify({"error": "no images uploaded"}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "queued"}

    # Create job workdir synchronously and save incoming files to disk immediately
    job_dir = CONV_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    saved_image_paths = []
    try:
        for i, f in enumerate(image_files, start=1):
            # Determine extension
            filename = f.filename or f"img_{i}.jpg"
            ext = Path(filename).suffix or ".jpg"
            target = job_dir / f"img{i:03d}{ext}"
            # Save synchronously as string path
            f.save(str(target))
            # sanity: check file size saved
            size = os.path.getsize(str(target))
            print(f"[{job_id}] saved image {i}: {target} (size={size})")
            if size == 0:
                raise RuntimeError(f"Saved image is empty: {target}")
            saved_image_paths.append(str(target))

        saved_audio_path = None
        if audio_file:
            audio_ext = Path(audio_file.filename).suffix or ".mp3"
            audio_target = job_dir / f"audio{audio_ext}"
            audio_file.save(str(audio_target))
            size = os.path.getsize(str(audio_target))
            print(f"[{job_id}] saved audio: {audio_target} (size={size})")
            if size == 0:
                raise RuntimeError(f"Saved audio is empty: {audio_target}")
            saved_audio_path = str(audio_target)

    except Exception as e:
        tb = traceback.format_exc()
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"upload/save error: {e}; traceback: {tb}"
        print(f"[{job_id}] upload/save failed: {e}\n{tb}")
        return jsonify({"job_id": job_id, "status": "error", "error": str(e)}), 500

    # Mark processing and start background thread using file paths (not FileStorage objects)
    jobs[job_id]["status"] = "processing"
    thread = Thread(target=run_conversion, args=(job_id, saved_image_paths, saved_audio_path))
    thread.start()

    return jsonify({"job_id": job_id}), 202

@app.route("/api/status/<job_id>")
def status(job_id):
    info = jobs.get(job_id)
    if not info:
        return jsonify({"status": "not_found"}), 404
    return jsonify({"status": info.get("status"), "error": info.get("error", "")})


@app.route('/api/download/<job_id>')
def download(job_id):
    info = jobs.get(job_id)
    
    # 1. Check if job exists and is finished
    if not info or info.get('status') != 'done':
        return jsonify({"error": "File not ready or job not found"}), 404
    
    out_path = info.get('out_path')

    # 2. Verify the file actually exists on the filesystem
    if not out_path or not os.path.exists(out_path):
        return jsonify({"error": "File not found on disk"}), 404

    try:
        # 3. Use send_file with the direct absolute path
        return send_file(
            out_path, 
            as_attachment=True, 
            download_name=f"conversion_{job_id}.mp4",
            mimetype='video/mp4'
        )
    except Exception as e:
        return jsonify({"error": f"Download failed: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)