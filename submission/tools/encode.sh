#!/usr/bin/env bash
# Muxes the frames from make_video.py into docs/demo_video.mp4 (225s, beats per video_script.md).
set -euo pipefail
cd "$(dirname "$0")/../.."
FR="$PWD/../stage4a_frames"
cat > "$FR/concat.txt" <<LIST
file '$FR/b1_problem.png'
duration 15
file '$FR/b2_pillars.png'
duration 12
file '$FR/b2_dashboard.png'
duration 18
file '$FR/b3a_post.png'
duration 20
file '$FR/b3b_trace.png'
duration 20
file '$FR/b3c_armor.png'
duration 20
file '$FR/b3d_memory.png'
duration 30
file '$FR/b4_url.png'
duration 15
file '$FR/b4_overview.png'
duration 15
file '$FR/b4_registry.png'
duration 15
file '$FR/b4_tracelive.png'
duration 15
file '$FR/b5_diagram.png'
duration 20
file '$FR/b5_end.png'
duration 10
LIST
ffmpeg -y -f concat -safe 0 -i "$FR/concat.txt" -vf "fps=30,format=yuv420p" \
  -c:v libx264 -preset medium -crf 23 -movflags +faststart docs/demo_video.mp4 </dev/null
